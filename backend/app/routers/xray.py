from __future__ import annotations

from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission
from app.models import Admin
from app.schemas import KeyPairOut, OperationResult, XrayStatusOut
from app.services import xray as xray_service
from app.services.audit import write_audit
from app.services.routing import redact_config
from app.services.settings import set_setting


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
    if result['ok']:
        set_setting(db, 'xray_autostart', restart)
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
        result = xray_service.apply_config(db)
        if not result["ok"]:
            return OperationResult(ok=False, message=result["message"])
    except RuntimeError as exc:
        return OperationResult(ok=False, message=str(exc))
    set_setting(db, 'xray_autostart', True)
    write_audit(db, admin, "restart_xray", "xray", None, "راه‌اندازی مجدد Xray", get_client_ip(request))
    return OperationResult(ok=True, message="Xray راه‌اندازی مجدد شد.")


@router.post("/stop", response_model=OperationResult)
def stop(
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    set_setting(db, 'xray_autostart', False)
    db.commit()
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

import platform
import subprocess
from pathlib import Path


@router.get("/versions")
def get_versions(_: Admin = Depends(read_access)):
    current_status = xray_service.xray_status()
    raw_version = "Xray 26.3.27"
    binary_path = xray_service.settings.xray_binary
    if Path(binary_path).is_file():
        try:
            res = subprocess.run([binary_path, "version"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                raw_version = res.stdout.strip().split("\n")[0]
        except Exception:
            pass

    return {
        "current_version": raw_version,
        "running": current_status.get("running", False),
        "arch": f"{platform.system().lower()}/{platform.machine().lower()}",
        "available_channels": ["stable", "latest"],
        "known_releases": [
            {"version": "v26.3.27", "channel": "latest", "released_at": "2026-03-27"},
            {"version": "v25.12.8", "channel": "stable", "released_at": "2025-12-08"},
            {"version": "v25.10.15", "channel": "stable", "released_at": "2025-10-15"},
        ],
    }


@router.post("/version/change", response_model=OperationResult)
def change_version(
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    raise HTTPException(501, "تغییر باینری هسته از پنل هنوز پیاده‌سازی نشده است؛ نسخه با ذخیرهٔ یک تنظیم تغییر نمی‌کند.")


@router.post("/service/restart-all", response_model=OperationResult)
def restart_all_services(
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(write_access),
):
    try:
        result = xray_service.apply_config(db)
        if not result["ok"]:
            return OperationResult(ok=False, message=result["message"])
    except Exception as exc:
        return OperationResult(ok=False, message=f"خطا در راه‌اندازی مجدد هسته: {exc}")
    write_audit(db, admin, "restart_xray", "xray", None, "راه‌اندازی مجدد هستهٔ محلی Xray", get_client_ip(request))
    return OperationResult(ok=True, message="هستهٔ محلی Xray راه‌اندازی مجدد شد.")


@router.get("/singbox/status")
def singbox_status(_: Admin = Depends(read_access)):
    from app.services.singbox_runtime import status
    return status()


@router.post("/singbox/apply")
def apply_singbox(request: Request, db: Session = Depends(get_db), admin: Admin = Depends(write_access)):
    from app.services.singbox_runtime import apply
    try:
        result = apply(db)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
    set_setting(db, "singbox_enabled", True)
    db.commit()
    write_audit(db, admin, "apply_singbox", "core", None, "Sing-box configuration applied", get_client_ip(request))
    return result


@router.post("/singbox/stop")
def stop_singbox(request: Request, db: Session = Depends(get_db), admin: Admin = Depends(write_access)):
    from app.services.singbox_runtime import stop
    set_setting(db, "singbox_enabled", False)
    db.commit()
    with xray_service._control_lock:
        stop()
    write_audit(db, admin, "stop_singbox", "core", None, "Sing-box stopped", get_client_ip(request))
    return {"ok": True}


@router.get("/auxiliary/status")
def auxiliary_status(_: Admin = Depends(read_access)):
    from app.services import ssh_runtime, mtproto_runtime
    import shutil
    return {"ssh_listeners": list(ssh_runtime.listeners), "ssh_errors": ssh_runtime.errors.copy(), "mtg_installed": bool(shutil.which(xray_service.settings.mtg_binary)), "mtg_running": [key for key,row in mtproto_runtime.processes.copy().items() if row[1].poll() is None], "mtg_errors":mtproto_runtime.errors.copy()}
