from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission
from app.services.permissions import has_permission
from app.models import Admin, Inbound, Node
from app.schemas import NodeCreate, NodeOut, NodeUpdate, OperationResult
from app.services.audit import write_audit


router = APIRouter(prefix="/nodes", tags=["nodes"])
write_access = require_permission("nodes.manage")
read_access = require_permission("nodes.read")


def _node_out(node: Node, inbound_count: int) -> NodeOut:
    result = NodeOut.model_validate(node)
    result.inbound_count = inbound_count
    return result


@router.get("", response_model=list[NodeOut])
def list_nodes(db: Session = Depends(get_db), admin: Admin = Depends(read_access)):
    counts = dict(
        db.query(Inbound.node_id, func.count(Inbound.id))
        .group_by(Inbound.node_id)
        .all()
    )
    nodes = db.query(Node).order_by(Node.is_local.desc(), Node.id.asc()).all()
    output = [_node_out(node, counts.get(node.id, 0)) for node in nodes]
    if not has_permission(admin, "nodes.manage"):
        for item in output:
            item.api_key = ""
    return output


@router.post("", response_model=NodeOut, status_code=201)
def create_node(
    payload: NodeCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    node = Node(
        **payload.model_dump(),
        api_key=secrets.token_urlsafe(32),
        status="unknown",
        is_local=False,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    write_audit(
        db, admin, "create_node", "node", node.id, f"افزودن نود {node.name}", get_client_ip(request)
    )
    return _node_out(node, 0)


@router.patch("/{node_id}", response_model=NodeOut)
def update_node(
    node_id: int,
    payload: NodeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="نود پیدا نشد.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(node, key, value)
    db.commit()
    db.refresh(node)
    count = db.query(Inbound).filter(Inbound.node_id == node.id).count()
    write_audit(db, admin, "update_node", "node", node.id, f"ویرایش نود {node.name}", get_client_ip(request))
    return _node_out(node, count)


@router.post("/{node_id}/rotate-key", response_model=NodeOut)
def rotate_key(
    node_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="نود پیدا نشد.")
    node.api_key = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(node)
    count = db.query(Inbound).filter(Inbound.node_id == node.id).count()
    write_audit(db, admin, "rotate_node_key", "node", node.id, f"چرخش کلید نود {node.name}", get_client_ip(request))
    return _node_out(node, count)


@router.delete("/{node_id}", response_model=OperationResult)
def delete_node(
    node_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="نود پیدا نشد.")
    if node.is_local:
        raise HTTPException(status_code=400, detail="نود محلی قابل حذف نیست.")
    db.delete(node)
    db.commit()
    write_audit(db, admin, "delete_node", "node", node_id, f"حذف نود {node.name}", get_client_ip(request))
    return OperationResult(ok=True, message="نود حذف شد.")


@router.post("/{node_id}/heartbeat-check", response_model=NodeOut)
def heartbeat_check(
    node_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(read_access),
):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="نود پیدا نشد.")
    if not node.is_local and node.last_seen_at:
        last_seen = node.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last_seen).total_seconds() > 180:
            node.status = "offline"
            db.commit()
            db.refresh(node)
    count = db.query(Inbound).filter(Inbound.node_id == node.id).count()
    return _node_out(node, count)
