from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission
from app.models import Admin
from app.schemas import KeyPairOut, OperationResult, XrayStatusOut
from app.services import xray as xray_service
from app.services.audit import write_audit
from app.services.routing import redact_config


router = APIRouter(prefix="/xray", tags=["xray"])
write_access = require_permission("xray.manage")
read_access = require_permission("xray.manage")


@router.get("/status", response_model=XrayStatusOut)
def status(_: Admin = Depends(read_access)):
    return XrayStatusOut(**xray_service.xray_status())


@router.get("/config")
def preview_config(db: Session = Depends(get_db), _: Admin = Depends(read_access)):
    config, warnings, inbounds, client_count = xray_service.generate_config(db)
    return {
        "config": redact_config(config),
        "warnings": warnings,
        "inbound_count": len(inbounds),
        "client_count": client_count,
    }


@router.post("/apply")
def apply(
    request: Request,
    restart: bool = True,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    result = xray_service.apply_config(db, restart=restart)
    write_audit(
        db,
        admin,
        "apply_xray",
        "xray",
        None,
        f"اعمال کانفیگ Xray (موفق: {result['ok']})",
        get_client_ip(request),
    )
    return result


@router.post("/restart", response_model=OperationResult)
def restart(
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    try:
        xray_service.restart_process()
    except RuntimeError as exc:
        return OperationResult(ok=False, message=str(exc))
    write_audit(db, admin, "restart_xray", "xray", None, "راه‌اندازی مجدد Xray", get_client_ip(request))
    return OperationResult(ok=True, message="Xray راه‌اندازی مجدد شد.")


@router.post("/stop", response_model=OperationResult)
def stop(
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    xray_service.stop_process()
    write_audit(db, admin, "stop_xray", "xray", None, "توقف Xray", get_client_ip(request))
    return OperationResult(ok=True, message="Xray متوقف شد.")


@router.post("/sync-stats")
def sync_stats(
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    result = xray_service.sync_stats(db)
    write_audit(
        db,
        admin,
        "sync_xray_stats",
        "xray",
        None,
        f"همگام‌سازی آمار (موفق: {result['ok']})",
        get_client_ip(request),
    )
    return result


@router.post("/keys", response_model=KeyPairOut)
def keys(_: Admin = Depends(write_access)):
    return KeyPairOut(**xray_service.generate_keypair())
