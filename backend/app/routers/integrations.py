import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_admin, get_client_ip
from app.models import Admin, TelegramAdminBinding, TelegramCommandReceipt, Setting, ProtectedSetting
from app.services.settings import get_setting, set_setting
from app.services.vault import put_secret, get_secret, has_secret
from app.services.audit import write_audit
from app.services.backups import create_backup
from app.services.telegram_bot import TelegramClient, TelegramError, send_owner_backup
from app.services.notifications import get_notification_config, send_smtp_email, send_discord_webhook

router = APIRouter(prefix="/integrations", tags=["integrations"])


def owner_only(admin: Admin = Depends(get_current_admin)):
    if not admin.is_owner:
        raise HTTPException(status_code=403, detail="این عملیات فقط برای مالک پنل مجاز است.")
    return admin


class TelegramConfigUpdate(BaseModel):
    enabled: bool | None = None
    owner_id: int | None = Field(default=None, ge=1)
    backup_enabled: bool | None = None
    backup_hours: int | None = Field(default=None, ge=1, le=168)
    bot_token: SecretStr | None = None
    backup_password: SecretStr | None = None


class BindingRequest(BaseModel):
    telegram_user_id: int = Field(ge=1)
    admin_id: int = Field(ge=1)
    allow_create: bool = False


class BackupRequest(BaseModel):
    password: SecretStr | None = None


def public_config(db):
    return {
        "enabled": bool(get_setting(db, "telegram_enabled", False)),
        "owner_id": get_setting(db, "telegram_owner_id", None),
        "backup_enabled": bool(get_setting(db, "telegram_backup_enabled", False)),
        "backup_hours": int(get_setting(db, "telegram_backup_hours", 24)),
        "token_configured": has_secret(db, "telegram_bot_token"),
        "backup_password_configured": has_secret(db, "backup_password"),
        "last_backup_at": get_setting(db, "telegram_last_backup_at", None),
    }


@router.get("/telegram")
def read_telegram(db: Session = Depends(get_db), _: Admin = Depends(owner_only)):
    return public_config(db)


@router.put("/telegram")
def update_telegram(payload: TelegramConfigUpdate, request: Request, db: Session = Depends(get_db), actor: Admin = Depends(owner_only)):
    data = payload.model_dump(exclude_unset=True)
    if any(value is None for value in data.values()):
        raise HTTPException(status_code=422, detail="برای حذف تنظیمات ربات از عملیات حذف استفاده کنید.")
    token = data.pop("bot_token", None)
    password = data.pop("backup_password", None)
    if token is not None:
        token = token.get_secret_value().strip()
        if not re.fullmatch(r"[0-9]{6,20}:[A-Za-z0-9_-]{30,}", token):
            raise HTTPException(status_code=400, detail="ساختار توکن ربات معتبر نیست.")
        put_secret(db, "telegram_bot_token", token)
        set_setting(db, "telegram_update_offset", 0)
        db.query(TelegramCommandReceipt).delete()
    if token is not None or data.get("enabled") is True or "owner_id" in data:
        set_setting(db, "telegram_valid_from", int(datetime.now(timezone.utc).timestamp()))
    if password is not None:
        password = password.get_secret_value()
        if not 16 <= len(password) <= 256:
            raise HTTPException(status_code=400, detail="رمز بکاپ باید بین ۱۶ و ۲۵۶ کاراکتر باشد.")
        put_secret(db, "backup_password", password)
    for key, value in data.items():
        set_setting(db, f"telegram_{key}", value)
    db.flush()
    config = public_config(db)
    if config["enabled"] and (not config["owner_id"] or not config["token_configured"]):
        raise HTTPException(status_code=400, detail="برای فعال‌سازی، توکن و شناسه عددی مالک لازم است.")
    if config["backup_enabled"] and not config["backup_password_configured"]:
        raise HTTPException(status_code=400, detail="برای بکاپ خودکار رمز بکاپ را تنظیم کنید.")
    if config["owner_id"] and db.get(TelegramAdminBinding, config["owner_id"]):
        raise HTTPException(status_code=409, detail="شناسه مالک قبلاً به یک مدیر متصل شده است؛ اتصال قبلی را حذف کنید.")
    db.commit()
    write_audit(db, actor, "configure_telegram", "integration", None, "تنظیم ربات و سیاست بکاپ", get_client_ip(request))
    return public_config(db)


@router.delete("/telegram")
def remove_telegram(request: Request, db: Session = Depends(get_db), actor: Admin = Depends(owner_only)):
    for row in db.query(Setting).filter(Setting.key.like("telegram_%")).all():
        db.delete(row)
    db.query(ProtectedSetting).filter(ProtectedSetting.key == "telegram_bot_token").delete()
    db.query(TelegramAdminBinding).delete()
    db.query(TelegramCommandReceipt).delete()
    db.commit()
    write_audit(db, actor, "remove_telegram", "integration", None, "قطع اتصال ربات", get_client_ip(request))
    return {"ok": True}


@router.post("/telegram/check")
def check_telegram(db: Session = Depends(get_db), _: Admin = Depends(owner_only)):
    token = get_secret(db, "telegram_bot_token")
    if not token:
        raise HTTPException(status_code=400, detail="توکن تنظیم نشده است.")
    try:
        identity = TelegramClient(token).call("getMe")
    except TelegramError:
        raise HTTPException(status_code=502, detail="ارتباط با ربات تأیید نشد؛ توکن و دسترسی شبکه را بررسی کنید.") from None
    return {"ok": True, "username": identity.get("username")}


@router.get("/telegram/admins")
def bindings(db: Session = Depends(get_db), _: Admin = Depends(owner_only)):
    return [{"telegram_user_id": b.telegram_user_id, "admin_id": b.admin_id, "allow_create": b.allow_create} for b in db.query(TelegramAdminBinding).all()]


@router.put("/telegram/admins")
def bind_admin(payload: BindingRequest, request: Request, db: Session = Depends(get_db), actor: Admin = Depends(owner_only)):
    if payload.telegram_user_id == get_setting(db, "telegram_owner_id", None):
        raise HTTPException(status_code=400, detail="شناسه مالک را به حساب مدیر متصل نکنید.")
    target = db.get(Admin, payload.admin_id)
    if target is None or target.is_owner:
        raise HTTPException(status_code=400, detail="حساب مدیر معتبر انتخاب کنید.")
    row = db.get(TelegramAdminBinding, payload.telegram_user_id)
    if row is None:
        row = TelegramAdminBinding(telegram_user_id=payload.telegram_user_id)
        db.add(row)
    row.admin_id, row.allow_create = payload.admin_id, payload.allow_create
    row.authorized_at = datetime.now(timezone.utc)
    db.commit()
    write_audit(db, actor, "bind_telegram_admin", "admin", target.id, "تنظیم دسترسی مدیر در ربات", get_client_ip(request))
    return {"ok": True}


@router.delete("/telegram/admins/{telegram_user_id}")
def unbind_admin(telegram_user_id: int, request: Request, db: Session = Depends(get_db), actor: Admin = Depends(owner_only)):
    row = db.get(TelegramAdminBinding, telegram_user_id)
    if row:
        db.delete(row)
        db.commit()
    write_audit(db, actor, "unbind_telegram_admin", "integration", None, "لغو اتصال مدیر ربات", get_client_ip(request))
    return {"ok": True}


@router.post("/backups/download")
def download_backup(payload: BackupRequest, request: Request, db: Session = Depends(get_db), actor: Admin = Depends(owner_only)):
    password = payload.password.get_secret_value() if payload.password else get_secret(db, "backup_password")
    if not password or not 16 <= len(password) <= 256:
        raise HTTPException(status_code=400, detail="رمز بکاپ حداقل ۱۶ کاراکتری لازم است.")
    try:
        name, content = create_backup(password)
    except (RuntimeError, OSError):
        raise HTTPException(status_code=503, detail="بکاپ ساخته نشد؛ اتصال دیتابیس و فضای موقت را بررسی کنید.") from None
    write_audit(db, actor, "download_backup", "backup", None, "دریافت بکاپ رمزگذاری‌شده", get_client_ip(request))
    return Response(content, media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.post("/backups/send")
def send_backup(request: Request, db: Session = Depends(get_db), actor: Admin = Depends(owner_only)):
    token = get_secret(db, "telegram_bot_token")
    if not token:
        raise HTTPException(status_code=400, detail="توکن ربات تنظیم نشده است.")
    try:
        send_owner_backup(TelegramClient(token), db)
    except (ValueError, RuntimeError, OSError):
        raise HTTPException(status_code=503, detail="ارسال بکاپ انجام نشد؛ تنظیمات ربات و بکاپ را بررسی کنید.") from None
    write_audit(db, actor, "send_owner_backup", "backup", None, "ارسال بکاپ رمزگذاری‌شده به مالک", get_client_ip(request))
    return {"ok": True}


class NotificationConfigUpdate(BaseModel):
    smtp_enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_sender: str | None = None
    smtp_recipient: str | None = None
    smtp_use_tls: bool | None = None
    discord_enabled: bool | None = None
    discord_webhook_url: SecretStr | None = None


@router.get("/notifications")
def read_notifications(db: Session = Depends(get_db), _: Admin = Depends(owner_only)):
    return get_notification_config(db)


@router.put("/notifications")
def update_notifications(
    payload: NotificationConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Admin = Depends(owner_only),
):
    data = payload.model_dump(exclude_unset=True)
    if "smtp_password" in data and payload.smtp_password:
        put_secret(db, "smtp_password", payload.smtp_password.get_secret_value())
        data.pop("smtp_password")
    if "discord_webhook_url" in data and payload.discord_webhook_url:
        put_secret(db, "discord_webhook_url", payload.discord_webhook_url.get_secret_value())
        data.pop("discord_webhook_url")

    for key, value in data.items():
        if value is not None:
            set_setting(db, key, value)

    db.commit()
    write_audit(db, actor, "configure_notifications", "integration", None, "تنظیمات اعلان‌های ایمیل و دیسکورد", get_client_ip(request))
    return get_notification_config(db)


@router.post("/notifications/test-email")
def test_email(
    request: Request,
    db: Session = Depends(get_db),
    actor: Admin = Depends(owner_only),
):
    ok, message = send_smtp_email(
        db,
        subject="[SpecterGate] تست ارسال ایمیل",
        content="این یک ایمیل آزمایشی از پنل مدیریت SpecterGate است. ارتباط سرور SMTP با موفقیت برقرار شد.",
    )
    if not ok:
        raise HTTPException(status_code=502, detail=message)
    write_audit(db, actor, "test_email", "integration", None, "تست ارسال ایمیل", get_client_ip(request))
    return {"ok": True, "message": message}


@router.post("/notifications/test-discord")
def test_discord(
    request: Request,
    db: Session = Depends(get_db),
    actor: Admin = Depends(owner_only),
):
    ok, message = send_discord_webhook(
        db,
        title="تست ارتباط با SpecterGate",
        description="این یک پیام آزمایشی از سیستم اعلان‌های SpecterGate است. وب‌هوک با موفقیت فعال شد.",
        color_hex=0x6366F1,
    )
    if not ok:
        raise HTTPException(status_code=502, detail=message)
    write_audit(db, actor, "test_discord", "integration", None, "تست وب‌هوک دیسکورد", get_client_ip(request))
    return {"ok": True, "message": message}
