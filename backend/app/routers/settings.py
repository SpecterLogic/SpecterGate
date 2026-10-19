from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission
from app.models import Admin, AuditLog
from app.schemas import AuditLogOut, SettingsOut, SettingsUpdate
from app.services.audit import write_audit
from app.services.settings import all_settings, set_setting


router = APIRouter(tags=["settings"])
write_access = require_permission("settings.manage")
read_access = require_permission("settings.read")
audit_access = require_permission("audit.read")


@router.get("/settings", response_model=SettingsOut)
def read_settings(db: Session = Depends(get_db), _: Admin = Depends(read_access)):
    values = all_settings(db)
    return SettingsOut(**{key: values.get(key) for key in SettingsOut.model_fields})


@router.put("/settings", response_model=SettingsOut)
def update_settings(
    payload: SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        set_setting(db, key, value)
    db.commit()
    write_audit(
        db,
        admin,
        "update_settings",
        "settings",
        None,
        "به‌روزرسانی تنظیمات پنل",
        get_client_ip(request),
    )
    values = all_settings(db)
    return SettingsOut(**{key: values.get(key) for key in SettingsOut.model_fields})


@router.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs(
    limit: int = 50,
    db: Session = Depends(get_db),
    _: Admin = Depends(audit_access),
):
    limit = max(1, min(limit, 200))
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
