from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_permission
from app.models import Admin, Inbound, Node, TrafficSample, VPNUser
from app.schemas import DashboardOverview, NodeOut, UserOut
from app.services.permissions import user_query_for, has_permission


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverview)
def overview(
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("dashboard.read")),
):
    users = user_query_for(db, admin).all()
    statuses: dict[str, int] = defaultdict(int)
    for user in users:
        statuses[user.status] += 1

    nodes = db.query(Node).order_by(Node.is_local.desc(), Node.id.asc()).all()
    inbound_counts = dict(
        db.query(Inbound.node_id, func.count(Inbound.id)).group_by(Inbound.node_id).all()
    )
    node_items: list[NodeOut] = []
    for node in nodes:
        item = NodeOut.model_validate(node)
        item.api_key = ""
        item.inbound_count = inbound_counts.get(node.id, 0)
        node_items.append(item)

    active_inbounds = db.query(Inbound).filter(Inbound.is_active.is_(True)).all()
    protocol_counts: dict[str, int] = defaultdict(int)
    for inbound in active_inbounds:
        protocol_counts[inbound.protocol] += 1

    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    samples = (
        db.query(TrafficSample)
        .filter(TrafficSample.recorded_at >= start, TrafficSample.user_id.in_([user.id for user in users]))
        .all()
    )
    daily: dict[str, dict[str, int]] = defaultdict(lambda: {"upload": 0, "download": 0})
    for sample in samples:
        sample_time = sample.recorded_at
        if sample_time.tzinfo is None:
            sample_time = sample_time.replace(tzinfo=timezone.utc)
        key = sample_time.date().isoformat()
        daily[key]["upload"] += int(sample.upload_bytes or 0)
        daily[key]["download"] += int(sample.download_bytes or 0)

    series = []
    for offset in range(7):
        key = (start + timedelta(days=offset)).date().isoformat()
        values = daily.get(key, {"upload": 0, "download": 0})
        series.append(
            {
                "date": key,
                "upload": values["upload"],
                "download": values["download"],
                "total": values["upload"] + values["download"],
            }
        )

    today_key = now.date().isoformat()
    today_values = daily.get(today_key, {"upload": 0, "download": 0})
    upload_total = sum(int(user.upload_bytes or 0) for user in users)
    download_total = sum(int(user.download_bytes or 0) for user in users)
    recent = sorted(users, key=lambda item: item.created_at, reverse=True)[:6]

    return DashboardOverview(
        total_users=len(users),
        active_users=statuses["active"],
        expired_users=statuses["expired"],
        limited_users=statuses["limited"],
        disabled_users=statuses["disabled"],
        total_nodes=len(nodes),
        online_nodes=sum(1 for node in nodes if node.is_online),
        total_inbounds=db.query(Inbound).count(),
        active_inbounds=len(active_inbounds),
        upload_bytes=upload_total,
        download_bytes=download_total,
        total_traffic_bytes=upload_total + download_total,
        today_traffic_bytes=today_values["upload"] + today_values["download"],
        traffic_series=series,
        protocol_series=[
            {"name": protocol, "value": count}
            for protocol, count in sorted(protocol_counts.items())
        ],
        recent_users=[UserOut.from_user(user) for user in recent],
        nodes=node_items if has_permission(admin, "nodes.read") else [],
    )
