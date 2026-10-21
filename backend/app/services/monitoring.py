from __future__ import annotations

import time
import uuid
import ipaddress
import grpc
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Inbound, VPNUser

_lock = RLock()

# tag -> (timestamp, upload_bytes, download_bytes)
_inbound_snapshots: dict[str, tuple[float, int, int]] = {}
# tag -> (upload_speed_bps, download_speed_bps)
_inbound_speeds: dict[str, tuple[float, float]] = {}

# Active client session tracking
# session_id -> dict: { session_id, user_id, username, client_ip, user_agent, last_seen_at }
_active_sessions: dict[str, dict[str, Any]] = {}
_last_core_poll = 0.0


def source_available():
    return time.time() - _last_core_poll < 20

SESSION_TTL_SECONDS = 600  # 10 minutes window for active session presence


def update_inbound_speed(tag: str, current_upload: int, current_download: int) -> None:
    now = time.time()
    with _lock:
        if tag in _inbound_snapshots:
            prev_time, prev_up, prev_down = _inbound_snapshots[tag]
            elapsed = now - prev_time
            if elapsed >= 1.0:
                up_speed = max(0.0, (current_upload - prev_up) / elapsed)
                down_speed = max(0.0, (current_download - prev_down) / elapsed)
                _inbound_speeds[tag] = (up_speed, down_speed)
                _inbound_snapshots[tag] = (now, current_upload, current_download)
        else:
            _inbound_snapshots[tag] = (now, current_upload, current_download)
            _inbound_speeds[tag] = (0.0, 0.0)


def get_inbound_speeds(db: Session) -> list[dict[str, Any]]:
    with _lock:
        inbounds = db.query(Inbound).all()
        results = []
        for ib in inbounds:
            # Update snapshot
            up_bytes = int(ib.upload_bytes or 0)
            down_bytes = int(ib.download_bytes or 0)
            update_inbound_speed(ib.tag, up_bytes, down_bytes)

            up_speed, down_speed = _inbound_speeds.get(ib.tag, (0.0, 0.0))
            results.append({
                "inbound_id": ib.id,
                "tag": ib.tag,
                "remark": ib.remark,
                "protocol": ib.protocol,
                "network": ib.network,
                "port": ib.port,
                "is_active": ib.is_active,
                "upload_speed_bps": round(up_speed, 1),
                "download_speed_bps": round(down_speed, 1),
                "total_upload_bytes": up_bytes,
                "total_download_bytes": down_bytes,
            })
        return results


def cleanup_stale_sessions() -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=SESSION_TTL_SECONDS)
    with _lock:
        stale_keys = [
            sid for sid, s in _active_sessions.items()
            if s["last_seen_at"] < cutoff
        ]
        for sid in stale_keys:
            del _active_sessions[sid]


def register_user_session(
    db: Session,
    user: VPNUser,
    client_ip: str,
    user_agent: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    cleanup_stale_sessions()

    with _lock:
        # Find if session from this IP already exists for this user
        existing_sid = next(
            (sid for sid, s in _active_sessions.items() if s["user_id"] == user.id and s["client_ip"] == client_ip),
            None,
        )
        if existing_sid:
            _active_sessions[existing_sid]["last_seen_at"] = now
            if user_agent:
                _active_sessions[existing_sid]["user_agent"] = user_agent
            return existing_sid

        # Check device limit
        user_ips = {s["client_ip"] for s in _active_sessions.values() if s["user_id"] == user.id}
        if user.device_limit and user.device_limit > 0:
            if len(user_ips) >= user.device_limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"تعداد دستگاه‌های مجاز ({user.device_limit}) تکمیل شده است. لطفاً ارتباط قبلی را قطع کنید.",
                )

        sid = str(uuid.uuid4())
        _active_sessions[sid] = {
            "session_id": sid,
            "user_id": user.id,
            "username": user.username,
            "client_ip": client_ip,
            "user_agent": user_agent or "Unknown Client",
            "connected_at": now,
            "last_seen_at": now,
        }
        return sid


def get_active_sessions(user_id: int | None = None) -> list[dict[str, Any]]:
    cleanup_stale_sessions()
    with _lock:
        sessions = list(_active_sessions.values())
        if user_id is not None:
            sessions = [s for s in sessions if s["user_id"] == user_id]
        return sorted(sessions, key=lambda s: s["last_seen_at"], reverse=True)


def terminate_session(session_id: str) -> bool:
    with _lock:
        if session_id in _active_sessions:
            del _active_sessions[session_id]
            return True
        return False


def terminate_user_sessions(user_id: int) -> int:
    with _lock:
        to_del = [sid for sid, s in _active_sessions.items() if s["user_id"] == user_id]
        for sid in to_del:
            del _active_sessions[sid]
        return len(to_del)


def blocks(db):
    from app.services.settings import get_setting
    entries = get_setting(db, "runtime_session_blocks", []) or []
    return [row for row in entries if row["until"] > time.time()]


def block_session(db, user, ip):
    from app.services.settings import set_setting
    address = str(ipaddress.ip_address(ip))
    entries = [row for row in blocks(db) if (row["user"], row["ip"]) != (user.uuid, address)]
    entries.append({"user": user.uuid, "ip": address, "until": time.time() + 600})
    set_setting(db, "runtime_session_blocks", entries)
    db.commit()


def refresh_from_core(db):
    """Read native logical flows; never restart the core to enforce IP limits."""
    from app.services import session_control, xray_rpc
    global _last_core_poll
    try:
        session_control.sync(db)
        snapshot = session_control.call("Snapshot")
        observations = {}
        for flow in snapshot["flows"]:
            observations.setdefault(flow["user"], {})[flow["ip"]] = flow["since"]
        emails = list(observations)
    except (grpc.RpcError, RuntimeError):
        # Legacy cores remain observable, but cannot enforce targeted limits.
        try:
            emails = xray_rpc.online_users()
            observations = {email: {address.strip("[]"): timestamp for address, timestamp in xray_rpc.online_ips(email).items()} for email in emails}
        except grpc.RpcError:
            return False
    _last_core_poll = time.time()
    users = {user.uuid: user for user in db.query(VPNUser).filter(VPNUser.uuid.in_(emails)).all()}
    changed = False
    excluded = {(row["user"], row["ip"]) for row in blocks(db)}
    with _lock:
        # Native snapshots are authoritative; expired/disconnected IPs release slots.
        for sid, session in list(_active_sessions.items()):
            user = db.get(VPNUser, session["user_id"])
            if user is None or session["client_ip"] not in observations.get(user.uuid, {}):
                del _active_sessions[sid]
    for email, ips in observations.items():
        user = users.get(email)
        if user is None:
            continue
        for address, timestamp in sorted(ips.items(), key=lambda item: item[1]):
            try:
                address = str(ipaddress.ip_address(address))
            except ValueError:
                continue
            if (email, address) in excluded:
                continue
            # Observation must not enforce limits a second time in Python.
            with _lock:
                sid = next((sid for sid, row in _active_sessions.items() if row["user_id"] == user.id and row["client_ip"] == address), str(uuid.uuid4()))
                previous = _active_sessions.get(sid, {})
                now = datetime.now(timezone.utc)
                _active_sessions[sid] = {"session_id": sid, "user_id": user.id, "username": user.username, "client_ip": address, "user_agent": "Xray native logical flow", "connected_at": previous.get("connected_at", now), "last_seen_at": now}
    return changed
