from __future__ import annotations

from email.message import EmailMessage
import logging
import ssl
import smtplib
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.services.settings import get_setting, set_setting
from app.services.vault import get_secret, has_secret, put_secret

logger = logging.getLogger(__name__)


def get_notification_config(db: Session) -> dict[str, Any]:
    return {
        # SMTP
        "smtp_enabled": bool(get_setting(db, "smtp_enabled", False)),
        "smtp_host": get_setting(db, "smtp_host", ""),
        "smtp_port": int(get_setting(db, "smtp_port", 587) or 587),
        "smtp_username": get_setting(db, "smtp_username", ""),
        "smtp_password_configured": has_secret(db, "smtp_password"),
        "smtp_sender": get_setting(db, "smtp_sender", ""),
        "smtp_recipient": get_setting(db, "smtp_recipient", ""),
        "smtp_use_tls": bool(get_setting(db, "smtp_use_tls", True)),
        # Discord
        "discord_enabled": bool(get_setting(db, "discord_enabled", False)),
        "discord_webhook_configured": has_secret(db, "discord_webhook_url"),
    }


def send_smtp_email(
    db: Session,
    subject: str,
    content: str,
    recipient: str | None = None,
    timeout: float = 8.0,
) -> tuple[bool, str]:
    """Send an email notification via configured SMTP server."""
    host = get_setting(db, "smtp_host", "")
    port = int(get_setting(db, "smtp_port", 587) or 587)
    username = get_setting(db, "smtp_username", "")
    password = get_secret(db, "smtp_password")
    sender = get_setting(db, "smtp_sender", "") or username
    target = recipient or get_setting(db, "smtp_recipient", "")
    use_tls = bool(get_setting(db, "smtp_use_tls", True))

    if not host or not target:
        return False, "تنظیمات سرور SMTP یا آدرس گیرنده ایمیل کامل نیست."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = target
    msg.set_content(content)

    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
            if use_tls:
                server.starttls(context=ssl.create_default_context())

        with server:
            if username and password:
                server.login(username, password)
            server.send_message(msg)
        return True, "ایمیل با موفقیت ارسال شد."
    except Exception as exc:
        logger.error("SMTP error sending email to %s: %s", target, exc)
        return False, f"خطا در ارسال ایمیل: {exc}"


def send_discord_webhook(
    db: Session,
    title: str,
    description: str,
    color_hex: int = 0x6366F1,
    timeout: float = 6.0,
) -> tuple[bool, str]:
    """Send an embed message to the configured Discord Webhook."""
    webhook_url = get_secret(db, "discord_webhook_url")
    if not webhook_url:
        return False, "آدرس وب‌هوک Discord تنظیم نشده است."

    payload = {
        "username": "SpecterGate Alerts",
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color_hex,
                "footer": {"text": "SpecterGate Notification System"},
            }
        ],
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(webhook_url, json=payload)
            if resp.status_code in (200, 204):
                return True, "پیام با موفقیت به دیسکورد ارسال شد."
            return False, f"خطای پاسخ سرور دیسکورد ({resp.status_code}): {resp.text[:100]}"
    except Exception as exc:
        logger.error("Discord webhook dispatch failed (%s)", type(exc).__name__)
        return False, "Discord connection failed. Check the webhook and network settings."


def dispatch_notification(
    db: Session,
    title: str,
    message: str,
    severity: str = "info",
) -> dict[str, Any]:
    """Unified notification dispatcher across Email, Discord and Telegram."""
    results: dict[str, Any] = {}

    # Email
    if get_setting(db, "smtp_enabled", False):
        ok, msg = send_smtp_email(db, f"[SpecterGate] {title}", message)
        results["email"] = {"ok": ok, "message": msg}

    # Discord
    if get_setting(db, "discord_enabled", False):
        color = 0xEF4444 if severity == "danger" else 0xF59E0B if severity == "warning" else 0x10B981
        ok, msg = send_discord_webhook(db, title, message, color_hex=color)
        results["discord"] = {"ok": ok, "message": msg}

    return results



def enqueue(db, event_key, title, message):
    from app.models import NotificationEvent
    for channel, flag in (("email", "smtp_enabled"), ("discord", "discord_enabled")):
        key = event_key + ":" + channel
        pending = any(isinstance(row, NotificationEvent) and row.event_key == key for row in db.new)
        if get_setting(db, flag, False) and not pending and not db.query(NotificationEvent).filter_by(event_key=key).first():
            db.add(NotificationEvent(event_key=key, title=title, message=message, channel=channel))


def deliver_pending(db):
    from app.models import NotificationEvent, as_utc
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    rows = db.query(NotificationEvent).filter(NotificationEvent.delivered_at.is_(None), NotificationEvent.attempts < 8, NotificationEvent.next_attempt_at <= now).order_by(NotificationEvent.id).limit(4).all()
    for row in rows:
        if not get_setting(db, "smtp_enabled" if row.channel == "email" else "discord_enabled", False):
            continue
        row.attempts += 1
        row.next_attempt_at = now + timedelta(seconds=min(3600, 30 * 2 ** row.attempts))
        db.commit()
        if row.channel == "email":
            ok, _ = send_smtp_email(db, row.title, row.message)
        else:
            ok, _ = send_discord_webhook(db, row.title, row.message)
        if ok:
            row.delivered_at = datetime.now(timezone.utc)
            db.commit()
    # Delivery is at-least-once: a provider receipt cannot be committed atomically
    # with the local database. A crash after receipt can cause a duplicate.


async def run(stop):
    import asyncio
    from app.database import SessionLocal
    def deliver():
        with SessionLocal() as db:
            deliver_pending(db)
    while not stop.is_set():
        try:
            await asyncio.to_thread(deliver)
        except Exception:
            logger.error("Notification worker could not process its queue.")
        try:
            await asyncio.wait_for(stop.wait(),timeout=10)
        except TimeoutError:
            pass
