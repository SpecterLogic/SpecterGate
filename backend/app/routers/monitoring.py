from __future__ import annotations

import grpc
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.deps import get_client_ip, get_db, require_permission
from app.models import Admin, VPNUser
from app.services.audit import write_audit
from app.services.monitoring import (
    get_active_sessions,
    get_inbound_speeds,
    terminate_session,
    terminate_user_sessions,
)
from app.services.permissions import ensure_user_access, user_query_for, require
from app.services import xray, session_control
from app.services.monitoring import block_session


def enforce_disconnect(db, users_and_ips):
    if not xray.xray_status()["running"]:
        raise HTTPException(503, "The local core is not running; no disconnection was performed.")
    with xray._control_lock:
        if not session_control.available():
            raise HTTPException(503, "Upgrade to the managed SpecterGate core for targeted disconnection. No core restart was performed.")
        for user, address in users_and_ips:
            block_session(db, user, address)
        try:
            session_control.sync(db)
        except (grpc.RpcError, RuntimeError) as error:
            raise HTTPException(503, "Disconnect could not be confirmed; the temporary block is saved for retry.") from error

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/status")
def source_status(admin: Admin = Depends(require_permission("users.read"))):
    from app.services.monitoring import source_available
    running = xray.xray_status()["running"]
    return {"available": running and source_available(), "targeted_control": running and session_control.available(), "scope": "local-xray-public-ips"}


@router.get("/speeds")
def read_inbound_speeds(
    admin: Admin = Depends(require_permission("inbounds.read")),
    db: Session = Depends(get_db),
):
    return get_inbound_speeds(db)


@router.get("/sessions")
def list_active_sessions(
    user_id: int | None = Query(default=None),
    admin: Admin = Depends(require_permission("users.read")),
    db: Session = Depends(get_db),
):
    if user_id is not None:
        user = db.get(VPNUser, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
        ensure_user_access(db, admin, user)
    visible_ids = {row.id for row in user_query_for(db, admin).all()}
    return [session for session in get_active_sessions(user_id) if session["user_id"] in visible_ids]


@router.post("/sessions/{session_id}/terminate")
def terminate_single_session(
    session_id: str,
    request: Request,
    admin: Admin = Depends(require_permission("users.write")),
    db: Session = Depends(get_db),
):
    session = next((item for item in get_active_sessions() if item["session_id"] == session_id), None)
    if session is None:
        raise HTTPException(status_code=404, detail="نشست متصل یافت نشد.")
    user = db.get(VPNUser, session["user_id"])
    if user is None:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    ensure_user_access(db, admin, user)
    require(admin, "xray.manage")
    enforce_disconnect(db, [(user, session["client_ip"])])
    # The authoritative refresh can remove the already-closed session first.
    terminate_session(session_id)
    write_audit(
        db,
        admin,
        "terminate_session",
        "user_session",
        session_id,
        f"نشست متصل {session_id} قطع شد.",
        get_client_ip(request),
    )
    return {"ok": True, "message": "User/IP blocked for 10 minutes; matching flows closed without restarting the core."}


@router.post("/users/{user_id}/terminate-sessions")
def terminate_all_user_sessions(
    user_id: int,
    request: Request,
    admin: Admin = Depends(require_permission("users.write")),
    db: Session = Depends(get_db),
):
    user = db.get(VPNUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    ensure_user_access(db, admin, user)
    require(admin, "xray.manage")
    sessions = get_active_sessions(user_id)
    if sessions:
        enforce_disconnect(db, [(user, session["client_ip"]) for session in sessions])
    count = terminate_user_sessions(user_id)
    write_audit(
        db,
        admin,
        "terminate_all_sessions",
        "user_sessions",
        str(user_id),
        f"تمام نشست‌های فعال کاربر {user.username} ({count} دستگاه) قطع شدند.",
        get_client_ip(request),
    )
    return {"ok": True, "terminated_count": count}
