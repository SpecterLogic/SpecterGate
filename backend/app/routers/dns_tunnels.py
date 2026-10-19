from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission
from app.models import Admin, DnsTunnel, VPNUser, Inbound, TunnelGatewaySettings
from app.services.permissions import ensure_user_access, user_query_for, has_permission
from app.services.resource_access import tunnel_allowed
from app.schemas import (
    DnsKeyPairOut,
    DnsMultiplexerOut,
    DnsTunnelCreate,
    DnsTunnelOut,
    DnsTunnelSetupOut,
    DnsTunnelUpdate,
    OperationResult,
)
from app.services.audit import write_audit
from app.services.dns import (
    dns_links_for_user,
    generate_keypair,
    multiplexer_config,
    server_setup,
    slipnet_uri,
)


router = APIRouter(prefix="/dns-tunnels", tags=["dns-tunnels"])
write_access = require_permission("dns.manage")
read_access = require_permission("dns.read")
HEX_KEY = re.compile(r"^[0-9a-fA-F]{64}$")


def _normalize(payload: dict) -> dict:
    if "domain" in payload and payload["domain"]:
        payload["domain"] = payload["domain"].strip().strip(".").lower()
    return payload


def _validate_port(db: Session, port: int, exclude_id: int | None = None) -> None:
    query = db.query(DnsTunnel).filter(DnsTunnel.upstream_port == port)
    if exclude_id is not None:
        query = query.filter(DnsTunnel.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=409, detail="پورت محلی این تونل قبلاً استفاده شده است.")


def _validate_gateway(db, host, port, enabled, exclude_id=None):
    if not enabled:
        return
    from ipaddress import ip_address
    from app.config import settings
    try:
        if not ip_address(host).is_loopback:
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=400, detail="دروازه مدیریت‌شده فقط روی آدرس loopback مثل 127.0.0.1 اجرا می‌شود.")
    if port == int(settings.xray_api_address.rsplit(":", 1)[-1]) or port == 8000 or db.query(Inbound).filter(Inbound.port == port).first():
        raise HTTPException(status_code=409, detail="پورت دروازه با سرویس دیگری تداخل دارد.")
    for tunnel in db.query(DnsTunnel).all():
        if tunnel.id != exclude_id and tunnel.managed_gateway and tunnel.target_host == host and tunnel.target_port == port:
            raise HTTPException(status_code=409, detail="هر تونل مدیریت‌شده باید پورت SOCKS اختصاصی داشته باشد.")


@router.get("", response_model=list[DnsTunnelOut])
def list_tunnels(db: Session = Depends(get_db), admin: Admin = Depends(read_access)):
    result = [DnsTunnelOut.model_validate(t) for t in db.query(DnsTunnel).order_by(DnsTunnel.created_at.desc()).all()]
    if not has_permission(admin, "dns.manage"):
        for item in result:
            item.private_key = ""
    return result


@router.post("/generate-keys", response_model=DnsKeyPairOut)
def create_keys(_: Admin = Depends(write_access)):
    return DnsKeyPairOut(**generate_keypair())


@router.get("/multiplexer", response_model=DnsMultiplexerOut)
def multiplexer(db: Session = Depends(get_db), _: Admin = Depends(read_access)):
    tunnels = db.query(DnsTunnel).filter(DnsTunnel.is_active.is_(True)).order_by(DnsTunnel.id.asc()).all()
    return DnsMultiplexerOut(**multiplexer_config(tunnels))


@router.post("", response_model=DnsTunnelOut, status_code=201)
def create_tunnel(
    payload: DnsTunnelCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    data = _normalize(payload.model_dump())
    managed_gateway = data.pop("managed_gateway")
    _validate_gateway(db, data["target_host"], data["target_port"], managed_gateway)
    if db.query(DnsTunnel).filter(DnsTunnel.domain == data["domain"]).first():
        raise HTTPException(status_code=409, detail="این دامنه قبلاً ثبت شده است.")
    _validate_port(db, data["upstream_port"])

    keys = generate_keypair()
    private_key = data.get("private_key") or keys["private_key"]
    public_key = data.get("public_key") or keys["public_key"]
    if not HEX_KEY.match(private_key) or not HEX_KEY.match(public_key):
        raise HTTPException(status_code=400, detail="کلیدهای DNSTT باید ۶۴ کاراکتر hex باشند.")
    data["private_key"] = private_key.lower()
    data["public_key"] = public_key.lower()

    tunnel = DnsTunnel(**data)
    tunnel.gateway_config = TunnelGatewaySettings(enabled=managed_gateway)
    db.add(tunnel)
    db.commit()
    db.refresh(tunnel)
    write_audit(
        db,
        admin,
        "create_dns_tunnel",
        "dns_tunnel",
        tunnel.id,
        f"ایجاد تونل DNS {tunnel.domain}",
        get_client_ip(request),
    )
    return tunnel


@router.get("/{tunnel_id}", response_model=DnsTunnelOut)
def get_tunnel(tunnel_id: int, db: Session = Depends(get_db), admin: Admin = Depends(read_access)):
    tunnel = db.get(DnsTunnel, tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="تونل DNS پیدا نشد.")
    output = DnsTunnelOut.model_validate(tunnel)
    if not has_permission(admin, "dns.manage"):
        output.private_key = ""
    return output


@router.patch("/{tunnel_id}", response_model=DnsTunnelOut)
def update_tunnel(
    tunnel_id: int,
    payload: DnsTunnelUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    tunnel = db.get(DnsTunnel, tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="تونل DNS پیدا نشد.")
    data = _normalize(payload.model_dump(exclude_unset=True))
    managed = data.pop("managed_gateway", tunnel.managed_gateway)
    if managed is None:
        raise HTTPException(status_code=422, detail="وضعیت دروازه نمی‌تواند خالی باشد.")
    _validate_gateway(db, data.get("target_host", tunnel.target_host), data.get("target_port", tunnel.target_port), managed, tunnel.id)
    if tunnel.gateway_config is None:
        tunnel.gateway_config = TunnelGatewaySettings(enabled=managed)
    else:
        tunnel.gateway_config.enabled = managed
    if "domain" in data and data["domain"] != tunnel.domain:
        if db.query(DnsTunnel).filter(DnsTunnel.domain == data["domain"]).first():
            raise HTTPException(status_code=409, detail="این دامنه قبلاً ثبت شده است.")
    if "upstream_port" in data:
        _validate_port(db, data["upstream_port"], exclude_id=tunnel.id)
    for key, value in data.items():
        setattr(tunnel, key, value)
    db.commit()
    db.refresh(tunnel)
    write_audit(
        db,
        admin,
        "update_dns_tunnel",
        "dns_tunnel",
        tunnel.id,
        f"ویرایش تونل DNS {tunnel.domain}",
        get_client_ip(request),
    )
    return tunnel


@router.delete("/{tunnel_id}", response_model=OperationResult)
def delete_tunnel(
    tunnel_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    tunnel = db.get(DnsTunnel, tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="تونل DNS پیدا نشد.")
    domain = tunnel.domain
    from app.services.resource_access import remove_resource_references
    remove_resource_references(db, tunnel.id, "tunnel_ids")
    db.delete(tunnel)
    db.commit()
    write_audit(
        db,
        admin,
        "delete_dns_tunnel",
        "dns_tunnel",
        tunnel_id,
        f"حذف تونل DNS {domain}",
        get_client_ip(request),
    )
    return OperationResult(ok=True, message="تونل DNS حذف شد.")


@router.get("/{tunnel_id}/setup", response_model=DnsTunnelSetupOut)
def setup(
    tunnel_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(write_access),
):
    tunnel = db.get(DnsTunnel, tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="تونل DNS پیدا نشد.")
    return DnsTunnelSetupOut(**server_setup(tunnel))


@router.get("/{tunnel_id}/runtime")
def tunnel_runtime(tunnel_id: int, request: Request, db: Session = Depends(get_db), _: Admin = Depends(write_access)):
    tunnel = db.get(DnsTunnel, tunnel_id)
    if tunnel is None:
        raise HTTPException(status_code=404, detail="تونل پیدا نشد.")
    gateway = request.app.state.tunnel_gateway
    return {"managed_gateway": tunnel.managed_gateway, "listening": tunnel.id in gateway.servers, "error": gateway.errors.get(tunnel.id), "endpoint": f"{tunnel.target_host}:{tunnel.target_port}"}


@router.get("/{tunnel_id}/link/{user_id}")
def user_link(
    tunnel_id: int,
    user_id: int,
    mode: str = "dnstt",
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    tunnel = db.get(DnsTunnel, tunnel_id)
    user = db.get(VPNUser, user_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="تونل DNS پیدا نشد.")
    if not user:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
    ensure_user_access(db, admin, user)
    if user.status != "active" or not tunnel_allowed(user, tunnel.id):
        raise HTTPException(status_code=403, detail="این کاربر مجاز به استفاده از تونل نیست.")
    if mode not in {"dnstt", "noizdns"}:
        raise HTTPException(status_code=400, detail="حالت باید dnstt یا noizdns باشد.")
    if mode == "noizdns" and not tunnel.noizdns_enabled:
        raise HTTPException(status_code=400, detail="NoizDNS برای این تونل فعال نیست.")
    return {
        "remark": f"{'NoizDNS' if mode == 'noizdns' else 'DNSTT'} · {tunnel.domain}",
        "uri": slipnet_uri(tunnel, user, mode),
    }


@router.get("/{tunnel_id}/user-links")
def all_user_links(
    tunnel_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    tunnel = db.get(DnsTunnel, tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="تونل DNS پیدا نشد.")
    users = user_query_for(db, admin).filter(VPNUser.is_active.is_(True)).order_by(VPNUser.id.asc()).all()
    return {
        "tunnel_id": tunnel.id,
        "domain": tunnel.domain,
        "links": [
            {"user_id": user.id, "username": user.username, **link}
            for user in users
            for link in dns_links_for_user(user, [tunnel])
        ],
    }
