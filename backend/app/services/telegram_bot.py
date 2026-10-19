"""Installation-specific administration bot. Only private, explicitly bound users act."""
import asyncio
import io
import json
import re
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Admin, TelegramAdminBinding, TelegramCommandReceipt, VPNUser
from app.schemas import UserCreate
from app.services.settings import get_setting, set_setting
from app.services.permissions import has_permission, ensure_user_access
from app.services.vault import get_secret
from app.services.backups import create_backup


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token):
        if not re.fullmatch(r"[0-9]{6,20}:[A-Za-z0-9_-]{30,}", token or ""):
            raise TelegramError("Invalid bot token format.")
        self._token = token

    def call(self, method, fields=None, file=None):
        if method not in {"getMe", "getUpdates", "sendMessage", "sendPhoto", "sendDocument"}:
            raise TelegramError("Unsupported bot operation.")
        fields = fields or {}
        headers = {"Content-Type": "application/json"}
        if file is None:
            body = json.dumps(fields).encode()
        else:
            field, filename, content, mime = file
            boundary = secrets.token_hex(24)
            chunks = []
            for key, value in fields.items():
                if isinstance(value, (bool, list, dict)):
                    value = json.dumps(value)
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            chunks += [f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode(), content, f'\r\n--{boundary}--\r\n'.encode()]
            body = b"".join(chunks)
            headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        request = urllib.request.Request(f"https://api.telegram.org/bot{self._token}/{method}", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                result = json.loads(response.read(2 * 1024 * 1024))
            if not result.get("ok"):
                raise TelegramError("Telegram rejected the request.")
            return result.get("result")
        except TelegramError:
            raise
        except Exception:
            # Transport exceptions can contain the request URL, which includes the token.
            raise TelegramError("Telegram request failed; check connectivity and bot permissions.") from None

    def text(self, chat, text):
        return self.call("sendMessage", {"chat_id": chat, "text": text, "protect_content": True})


def actor_for(db, sender):
    owner_id = int(get_setting(db, "telegram_owner_id", 0) or 0)
    if sender == owner_id:
        actor = db.query(Admin).filter(Admin.is_owner.is_(True), Admin.is_active.is_(True)).first()
        return actor, True
    binding = db.get(TelegramAdminBinding, sender)
    actor = db.get(Admin, binding.admin_id) if binding else None
    current, seen = actor, set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if not current.is_active:
            return None, False
        current = current.parent
    return (actor, binding.allow_create) if actor and actor.is_active else (None, False)


def subscription_url(db, user):
    base = str(get_setting(db, "subscription_base_url", "") or "").strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("ابتدا آدرس عمومی اشتراک را در پنل تنظیم کنید.")
    return f"{base}/sub/{user.sub_token}"


def deliver_user(client, chat, url):
    import qrcode
    buffer = io.BytesIO()
    qrcode.make(url).save(buffer, format="PNG")
    client.text(chat, f"لینک اشتراک:\n{url}")
    client.call("sendPhoto", {"chat_id": chat, "caption": "QR اشتراک", "protect_content": True}, ("photo", "subscription.png", buffer.getvalue(), "image/png"))


def send_owner_backup(client, db):
    password = get_secret(db, "backup_password")
    owner = int(get_setting(db, "telegram_owner_id", 0) or 0)
    if not password or owner <= 0:
        raise ValueError("رمز بکاپ و شناسه مالک باید در پنل تنظیم شوند.")
    filename, payload = create_backup(password)
    client.call("sendDocument", {"chat_id": owner, "caption": "SpecterGate · encrypted backup", "protect_content": True}, ("document", filename, payload, "application/octet-stream"))
    set_setting(db, "telegram_last_backup_at", datetime.now(timezone.utc).isoformat())
    db.commit()


def handle_update(client, update):
    message = update.get("message") or {}
    chat, sender = message.get("chat") or {}, message.get("from") or {}
    if chat.get("type") != "private" or chat.get("id") != sender.get("id") or sender.get("is_bot"):
        return
    sender_id = sender.get("id")
    text = message.get("text", "")
    if not isinstance(sender_id, int) or not isinstance(text, str) or len(text) > 512:
        return
    with SessionLocal() as db:
        if not get_setting(db, "telegram_enabled", False):
            return
        date = message.get("date")
        if not isinstance(date, int) or date < int(get_setting(db, "telegram_valid_from", 0) or 0):
            return
        actor, allow_create = actor_for(db, sender_id)
        if actor is None:
            return
        if not actor.is_owner:
            binding = db.get(TelegramAdminBinding, sender_id)
            from app.models import as_utc
            if binding is None or date < int(as_utc(binding.authorized_at).timestamp()):
                return
        parts = text.strip().split()
        command = parts[0].split("@")[0].lower() if parts else ""
        try:
            if command in {"/start", "/help"}:
                client.text(sender_id, "/new username days GiB [plan_id]\n/sub username\n/backup (فقط مالک)")
            elif command == "/backup":
                if not actor.is_owner:
                    raise ValueError("بکاپ فقط برای مالک پنل قابل دریافت است.")
                send_owner_backup(client, db)
            elif command == "/sub":
                if len(parts) != 2 or not has_permission(actor, "users.read"):
                    raise ValueError("دستور معتبر: /sub username")
                user = db.query(VPNUser).filter(VPNUser.username == parts[1]).first()
                if user is None:
                    raise ValueError("کاربر پیدا نشد.")
                ensure_user_access(db, actor, user)
                deliver_user(client, sender_id, subscription_url(db, user))
            elif command == "/new":
                if not allow_create or not has_permission(actor, "users.write"):
                    raise ValueError("ساخت کاربر برای این حساب مجاز نیست.")
                if len(parts) not in {4, 5}:
                    raise ValueError("دستور معتبر: /new username days GiB [plan_id]")
                update_id = update.get("update_id")
                if not isinstance(update_id, int) or update_id < 0:
                    return
                previous = db.get(TelegramCommandReceipt, update_id)
                if previous:
                    if previous.admin_id != actor.id:
                        return
                    user = db.query(VPNUser).filter(VPNUser.username == previous.username, VPNUser.created_by == actor.id).first()
                    if user is None:
                        raise ValueError("کاربر این دستور قبلاً حذف شده است.")
                else:
                    recent = db.query(func.count(TelegramCommandReceipt.update_id)).filter(TelegramCommandReceipt.admin_id == actor.id, TelegramCommandReceipt.created_at > datetime.now(timezone.utc) - timedelta(minutes=1)).scalar()
                    if recent >= 10:
                        raise ValueError("حداکثر ده دستور ساخت در دقیقه مجاز است.")
                    days, volume = int(parts[2]), Decimal(parts[3])
                    if not 1 <= days <= 3650 or not volume.is_finite() or not 0 < volume <= 1_000_000:
                        raise ValueError("روز باید بین ۱ و ۳۶۵۰ و حجم، عددی مثبت بر حسب GiB باشد.")
                    payload = UserCreate(username=parts[1], expire_at=datetime.now(timezone.utc) + timedelta(days=days), data_limit_bytes=int(volume * 1024**3), plan_id=int(parts[4]) if len(parts) == 5 else None)
                    # Validate the public URL before creating anything.
                    subscription_url(db, type("Pending", (), {"sub_token": "pending"})())
                    db.add(TelegramCommandReceipt(update_id=update_id, admin_id=actor.id, username=payload.username))
                    db.flush()
                    from app.routers.users import create_user
                    request = Request({"type": "http", "method": "POST", "path": "/telegram/new", "headers": [], "client": ("telegram", 0)})
                    created = create_user(payload=payload, request=request, db=db, admin=actor)
                    user = db.get(VPNUser, created.id)
                ensure_user_access(db, actor, user)
                deliver_user(client, sender_id, subscription_url(db, user))
        except IntegrityError:
            db.rollback()
        except HTTPException as exc:
            db.rollback()
            client.text(sender_id, str(exc.detail))
        except (ValueError, InvalidOperation):
            db.rollback()
            client.text(sender_id, "دستور انجام نشد؛ نام کاربری، روز، حجم، پلن و تنظیمات اشتراک را بررسی کنید.")


def cycle():
    with SessionLocal() as db:
        if not get_setting(db, "telegram_enabled", False):
            return False
        token = get_secret(db, "telegram_bot_token")
        if not token:
            return False
        offset = int(get_setting(db, "telegram_update_offset", 0) or 0)
        client = TelegramClient(token)
    updates = client.call("getUpdates", {"offset": offset, "timeout": 10, "allowed_updates": ["message"], "limit": 20}) or []
    for update in updates:
        with SessionLocal() as db:
            if get_secret(db, "telegram_bot_token") != token:
                return True
        handle_update(client, update)
        with SessionLocal() as db:
            set_setting(db, "telegram_update_offset", int(update["update_id"]) + 1)
            db.commit()
    with SessionLocal() as db:
        if not get_setting(db, "telegram_enabled", False) or get_secret(db, "telegram_bot_token") != token:
            return True
        enabled = get_setting(db, "telegram_backup_enabled", False)
        hours = int(get_setting(db, "telegram_backup_hours", 24))
        last = get_setting(db, "telegram_last_backup_at", None)
        attempt = get_setting(db, "telegram_backup_attempt_at", None)
        now = datetime.now(timezone.utc)
        if enabled and (not last or now - datetime.fromisoformat(last) >= timedelta(hours=hours)) and (not attempt or now - datetime.fromisoformat(attempt) >= timedelta(minutes=15)):
            set_setting(db, "telegram_backup_attempt_at", now.isoformat())
            db.commit()
            send_owner_backup(client, db)
    return True


async def run(stop):
    import logging
    logger = logging.getLogger(__name__)
    while not stop.is_set():
        try:
            active = await asyncio.to_thread(cycle)
            delay = 1 if active else 5
        except Exception:
            # Deliberately omit exception objects containing transport URLs or user data.
            logger.warning("Telegram worker could not complete its cycle.")
            delay = 15
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass
