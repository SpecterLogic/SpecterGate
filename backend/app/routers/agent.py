from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Node, TrafficSample, VPNUser, NodeUsageReceipt
from sqlalchemy.exc import IntegrityError
from sqlalchemy import update
from app.services.xray import config_hash, generate_config


router = APIRouter(prefix="/agent", tags=["node-agent"])


def get_node(
    x_node_key: str = Header(..., alias="X-Node-Key"),
    db: Session = Depends(get_db),
) -> Node:
    node = db.query(Node).filter(Node.api_key == x_node_key, Node.is_local.is_(False)).first()
    if node is None:
        raise HTTPException(status_code=401, detail="کلید نود معتبر نیست.")
    return node


class HeartbeatPayload(BaseModel):
    cpu_usage: float = Field(default=0, ge=0, le=100)
    memory_usage: float = Field(default=0, ge=0, le=100)
    status: str = Field(default="online", pattern="^(online|degraded)$")


class UsageEntry(BaseModel):
    uuid: str
    upload: int = Field(default=0, ge=0)
    download: int = Field(default=0, ge=0)
    inbound_tag: str | None = None


class UsageReport(BaseModel):
    batch_id: str | None = Field(default=None, min_length=1, max_length=64)
    entries: list[UsageEntry] = Field(default_factory=list, max_length=5000)


@router.get("/config")
def node_config(node: Node = Depends(get_node), db: Session = Depends(get_db)):
    config, warnings, inbounds, client_count = generate_config(db, node=node)
    return {
        "hash": config_hash(config),
        "version": settings.version,
        "config": config,
        "warnings": warnings,
        "inbound_count": len(inbounds),
        "client_count": client_count,
        "api_address": f"127.0.0.1:{node.api_port or 10085}",
    }


@router.post("/heartbeat")
def heartbeat(payload: HeartbeatPayload, node: Node = Depends(get_node), db: Session = Depends(get_db)):
    node.status = payload.status
    node.cpu_usage = payload.cpu_usage
    node.memory_usage = payload.memory_usage
    node.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "ok": True,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "config_check_seconds": 60,
    }


@router.post("/usage")
def report_usage(payload: UsageReport, node: Node = Depends(get_node), db: Session = Depends(get_db)):
    if payload.batch_id:
        if db.get(NodeUsageReceipt, (node.id, payload.batch_id)) is not None:
            return {"ok": True, "updated": 0, "duplicate": True}
        db.add(NodeUsageReceipt(node_id=node.id, batch_id=payload.batch_id))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return {"ok": True, "updated": 0, "duplicate": True}
    users = {user.uuid: user for user in db.query(VPNUser).all()}
    now = datetime.now(timezone.utc)
    coefficient = float(node.traffic_coefficient or 1.0)
    updated = 0
    for entry in payload.entries:
        user = users.get(entry.uuid)
        if user is None:
            continue
        upload = int(entry.upload * coefficient)
        download = int(entry.download * coefficient)
        if upload <= 0 and download <= 0:
            continue
        db.execute(update(VPNUser).where(VPNUser.id == user.id).values(upload_bytes=VPNUser.upload_bytes + upload, download_bytes=VPNUser.download_bytes + download))
        db.add(
            TrafficSample(
                user_id=user.id,
                node_id=node.id,
                upload_bytes=upload,
                download_bytes=download,
                recorded_at=now,
            )
        )
        updated += 1
    node.last_seen_at = now
    node.status = "online"
    db.commit()
    return {"ok": True, "updated": updated, "coefficient": coefficient}
