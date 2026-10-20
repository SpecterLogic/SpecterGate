import ipaddress
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_permission, get_client_ip
from app.models import Admin, VPNUser, WireGuardPeer
from app.services import wireguard
from app.services.audit import write_audit
from app.services.permissions import ensure_user_access

router = APIRouter(prefix="/wireguard", tags=["wireguard"])


class PeerRequest(BaseModel):
    endpoint_host: str | None = Field(default=None, max_length=253)

    @field_validator("endpoint_host")
    @classmethod
    def validate_host(cls, value):
        if not value:
            return None
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            if not re.fullmatch(r"(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", value):
                raise ValueError("Enter an IP address or hostname without a port.")
            return value


@router.get("/status")
def status(admin: Admin = Depends(require_permission("users.read"))):
    state = wireguard.server_status()
    return {"ready": bool(state.get("ready")), "port": state.get("port", 51820), "protocol": "wireguard", "network": "IPv4"}


@router.post("/users/{user_id}")
def provision(user_id: int, payload: PeerRequest, request: Request, db: Session = Depends(get_db), admin: Admin = Depends(require_permission("settings.manage"))):
    user = db.get(VPNUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    ensure_user_access(db, admin, user)
    if not wireguard.server_status().get("ready"):
        raise HTTPException(409, "ابتدا سرویس بومی WireGuard را روی سرور نصب کنید.")
    if user.status != "active":
        raise HTTPException(409, "کاربر فعال نیست.")
    with wireguard.LOCK:
        peer = wireguard.provision(db, user)
        db.commit()
        wireguard.reconcile(db)
    write_audit(db, admin, "provision_wireguard", "user", user.id, "Native WireGuard access granted", get_client_ip(request))
    return {"config": wireguard.client_config(db, peer, payload.endpoint_host), "filename": f"{user.username}-wg.conf"}


@router.delete("/users/{user_id}")
def revoke(user_id: int, request: Request, db: Session = Depends(get_db), admin: Admin = Depends(require_permission("settings.manage"))):
    user = db.get(VPNUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    ensure_user_access(db, admin, user)
    peer = db.query(WireGuardPeer).filter_by(user_id=user_id).first()
    if peer:
        peer.is_active = False
        db.commit()
        wireguard.reconcile(db)
    write_audit(db, admin, "revoke_wireguard", "user", user.id, "Native WireGuard access revoked", get_client_ip(request))
    return {"ok": True}
