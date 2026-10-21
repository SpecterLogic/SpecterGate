from __future__ import annotations

from typing import Any
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
from app.services.permissions import ensure_user_access

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


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
    return get_active_sessions(user_id)


@router.post("/sessions/{session_id}/terminate")
def terminate_single_session(
    session_id: str,
    request: Request,
    admin: Admin = Depends(require_permission("users.write")),
    db: Session = Depends(get_db),
):
    found = terminate_session(session_id)
    if not found:
        raise HTTPException(status_code=404, detail="نشست متصل یافت نشد.")
    write_audit(
        db,
        admin,
        "terminate_session",
        "user_session",
        session_id,
        f"نشست متصل {session_id} قطع شد.",
        get_client_ip(request),
    )
    return {"ok": True}


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
