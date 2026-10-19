from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission
from app.models import Admin, Inbound, Node
from app.schemas import InboundCreate, InboundOut, InboundUpdate, KeyPairOut, OperationResult
from app.services.audit import write_audit
from app.services.xray import generate_keypair
from app.services.permissions import has_permission


router = APIRouter(prefix="/inbounds", tags=["inbounds"])
write_access = require_permission("inbounds.manage")
read_access = require_permission("inbounds.read")


def _inbound_out(inbound: Inbound, node: Node | None) -> InboundOut:
    result = InboundOut.model_validate(inbound)
    result.node_name = node.name if node else "Local"
    return result


def _validate_target(db: Session, node_id: int | None) -> None:
    if node_id is not None and db.get(Node, node_id) is None:
        raise HTTPException(status_code=404, detail="نود انتخاب‌شده پیدا نشد.")


@router.get("", response_model=list[InboundOut])
def list_inbounds(db: Session = Depends(get_db), admin: Admin = Depends(read_access)):
    inbounds = db.query(Inbound).order_by(Inbound.created_at.desc()).all()
    nodes = {node.id: node for node in db.query(Node).all()}
    output = [_inbound_out(inbound, nodes.get(inbound.node_id)) for inbound in inbounds]
    if not has_permission(admin, "inbounds.manage"):
        for item in output:
            item.reality_private_key = None
    return output


@router.post("", response_model=InboundOut, status_code=201)
def create_inbound(
    payload: InboundCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    if db.query(Inbound).filter(Inbound.tag == payload.tag).first():
        raise HTTPException(status_code=409, detail="تگ اینباند تکراری است.")
    _validate_target(db, payload.node_id)
    data = payload.model_dump()
    if data["node_id"] is None:
        local = db.query(Node).filter(Node.is_local.is_(True)).first()
        data["node_id"] = local.id if local else None

    if data["security"] == "reality":
        keys = generate_keypair()
        if not data.get("sni"):
            data["sni"] = "www.cloudflare.com"
        if not data.get("reality_dest"):
            data["reality_dest"] = "www.cloudflare.com:443"
        data["reality_private_key"] = data.get("reality_private_key") or keys["private_key"]
        data["reality_public_key"] = data.get("reality_public_key") or keys["public_key"]
        data["reality_short_id"] = data.get("reality_short_id") or keys["short_id"]
        if data["network"] == "tcp" and not data.get("flow"):
            data["flow"] = "xtls-rprx-vision"

    inbound = Inbound(**data)
    db.add(inbound)
    db.commit()
    db.refresh(inbound)
    write_audit(
        db,
        admin,
        "create_inbound",
        "inbound",
        inbound.id,
        f"ایجاد اینباند {inbound.tag}",
        get_client_ip(request),
    )
    return _inbound_out(inbound, db.get(Node, inbound.node_id) if inbound.node_id else None)


@router.post("/generate-keys", response_model=KeyPairOut)
def create_keys(_: Admin = Depends(write_access)):
    return KeyPairOut(**generate_keypair())


@router.get("/{inbound_id}", response_model=InboundOut)
def get_inbound(
    inbound_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(read_access),
):
    inbound = db.get(Inbound, inbound_id)
    if not inbound:
        raise HTTPException(status_code=404, detail="اینباند پیدا نشد.")
    output = _inbound_out(inbound, db.get(Node, inbound.node_id) if inbound.node_id else None)
    if not has_permission(admin, "inbounds.manage"):
        output.reality_private_key = None
    return output


@router.patch("/{inbound_id}", response_model=InboundOut)
def update_inbound(
    inbound_id: int,
    payload: InboundUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    inbound = db.get(Inbound, inbound_id)
    if not inbound:
        raise HTTPException(status_code=404, detail="اینباند پیدا نشد.")
    data = payload.model_dump(exclude_unset=True)
    if "tag" in data and data["tag"] != inbound.tag:
        if db.query(Inbound).filter(Inbound.tag == data["tag"]).first():
            raise HTTPException(status_code=409, detail="تگ اینباند تکراری است.")
    if "node_id" in data:
        _validate_target(db, data["node_id"])
    for key, value in data.items():
        setattr(inbound, key, value)
    db.commit()
    db.refresh(inbound)
    write_audit(
        db,
        admin,
        "update_inbound",
        "inbound",
        inbound.id,
        f"ویرایش اینباند {inbound.tag}",
        get_client_ip(request),
    )
    return _inbound_out(inbound, db.get(Node, inbound.node_id) if inbound.node_id else None)


@router.delete("/{inbound_id}", response_model=OperationResult)
def delete_inbound(
    inbound_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    inbound = db.get(Inbound, inbound_id)
    if not inbound:
        raise HTTPException(status_code=404, detail="اینباند پیدا نشد.")
    tag = inbound.tag
    from app.services.resource_access import remove_resource_references
    remove_resource_references(db, inbound.id, "inbound_ids")
    db.delete(inbound)
    db.commit()
    write_audit(
        db,
        admin,
        "delete_inbound",
        "inbound",
        inbound_id,
        f"حذف اینباند {tag}",
        get_client_ip(request),
    )
    return OperationResult(ok=True, message="اینباند حذف شد.")
