import hashlib
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.database import get_db
from app.deps import get_client_ip
from app.models import Admin
from app.routers.integrations import owner_only
from app.security import verify_password
from app.services import data_restore, xray, wireguard
from app.services.audit import write_audit
from app.services.backups import create_backup

router = APIRouter(prefix="/backups", tags=["backups"])


async def read_upload(file):
    value = await file.read(data_restore.MAX_UPLOAD + 1)
    if len(value) > data_restore.MAX_UPLOAD: raise HTTPException(413, "حداکثر اندازهٔ فایل ۱۶ مگابایت است.")
    return value


@router.post("/inspect")
async def inspect(file: UploadFile = File(), password: str = Form(min_length=16, max_length=256), _: Admin = Depends(owner_only)):
    payload = await read_upload(file)
    import asyncio
    try: data, _ = await asyncio.to_thread(data_restore.inspect, payload, password)
    except Exception: raise HTTPException(422, "فایل یا رمز بکاپ معتبر نیست یا این نسخه پشتیبانی نمی‌شود.") from None
    return {"fingerprint": hashlib.sha256(payload).hexdigest(), "counts": data_restore.summary(data), "preserves_admin_login": True}


@xray.serialized
def perform_restore(db, data, encrypted, password, payload, owner_id):
    with wireguard.LOCK:
        # An encrypted recovery snapshot exists before the first database change.
        _, rollback = create_backup(password)
        folder = BASE_DIR / "data" / "restore-rollbacks"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        recovery_id = secrets.token_hex(16)
        path = folder / f"{recovery_id}.sgbackup"
        path.write_bytes(rollback)
        path.chmod(0o600)
        data_restore.restore(db, data, encrypted, owner_id)
        # Stop old sessions/credentials; maintenance starts the restored config.
        runtime_warning = False
        try:
            xray.stop_process()
            wireguard.reconcile(db)
        except Exception:
            runtime_warning = True
        return recovery_id, runtime_warning


@router.post("/restore")
async def restore(request: Request, file: UploadFile = File(), password: str = Form(min_length=16, max_length=256), admin_password: str = Form(min_length=1, max_length=128), fingerprint: str = Form(min_length=64, max_length=64), confirmation: str = Form(), db: Session = Depends(get_db), actor: Admin = Depends(owner_only)):
    if confirmation != "RESTORE" or not verify_password(admin_password, actor.password_hash):
        raise HTTPException(403, "رمز ورود مالک یا تأیید بازیابی درست نیست.")
    payload = await read_upload(file)
    if not secrets.compare_digest(hashlib.sha256(payload).hexdigest(), fingerprint): raise HTTPException(409, "فایل با پیش‌نمایش مطابقت ندارد.")
    import asyncio
    try:
        data, encrypted = await asyncio.to_thread(data_restore.inspect, payload, password)
        recovery_id, runtime_warning = await asyncio.to_thread(perform_restore, db, data, encrypted, password, payload, actor.id)
    except Exception:
        raise HTTPException(422, "بازیابی انجام نشد؛ ساختار داده یا فضای دیسک را بررسی کنید. تراکنش ناموفق برگردانده شد.") from None
    write_audit(db, actor, "restore_data", "backup", None, "Owner restored users and configurations", get_client_ip(request))
    return {"ok": True, "counts": data_restore.summary(data), "rollback_id": recovery_id, "runtime_warning": runtime_warning}


@router.post("/rollback/{recovery_id}")
def download_recovery(recovery_id: str, _: Admin = Depends(owner_only)):
    import re
    if not re.fullmatch(r"[0-9a-f]{32}", recovery_id): raise HTTPException(404, "Backup not found")
    path = BASE_DIR / "data" / "restore-rollbacks" / f"{recovery_id}.sgbackup"
    if not path.is_file(): raise HTTPException(404, "Backup not found")
    return Response(path.read_bytes(), media_type="application/octet-stream", headers={"Content-Disposition": 'attachment; filename="before-restore.sgbackup"', "Cache-Control": "no-store"})
