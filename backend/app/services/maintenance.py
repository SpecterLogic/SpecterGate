"""Reconcile locally managed users and quotas without a manual Apply click."""
import asyncio
import json
import logging
import hashlib
from fastapi import HTTPException
from pathlib import Path

from app.config import settings
from app.database import SessionLocal
from app.services import xray
from app.services.settings import get_setting

logger = logging.getLogger(__name__)
_certificate_signature = None
_certificate_reload_pending = False


def certificate_changes(db):
    global _certificate_signature, _certificate_reload_pending
    from app.models import SslCertificate
    from app.services.ssl_manager import inspect_certificate
    for record in db.query(SslCertificate).filter(SslCertificate.is_active.is_(True)).all():
        try:
            details = inspect_certificate(Path(record.cert_path).read_text(encoding="utf-8"))
            record.issued_at, record.expires_at = details["issued_at"], details["expires_at"]
        except (OSError, ValueError, HTTPException):
            continue
    db.commit()
    values = []
    for inbound in db.query(Inbound).filter(Inbound.is_active.is_(True), Inbound.security == "tls").all():
        for path in (inbound.tls_cert_path, inbound.tls_key_path):
            if path:
                try:
                    values.append((path, hashlib.sha256(Path(path).read_bytes()).hexdigest()))
                except OSError:
                    values.append((path, "unavailable"))
    signature = tuple(sorted(values))
    changed = _certificate_signature is not None and signature != _certificate_signature
    _certificate_reload_pending = _certificate_reload_pending or changed
    _certificate_signature = signature
    return _certificate_reload_pending


from datetime import datetime, timezone
from app.models import Inbound, as_utc


def reconcile_inbounds(db: SessionLocal) -> None:
    now = datetime.now(timezone.utc)
    inbounds = db.query(Inbound).all()
    changed = False
    for inbound in inbounds:
        if inbound.reset_interval_days and inbound.reset_interval_days > 0:
            last = as_utc(inbound.last_reset_at) or as_utc(inbound.created_at) or now
            if (now - last).total_seconds() >= inbound.reset_interval_days * 86400:
                inbound.upload_bytes = 0
                inbound.download_bytes = 0
                inbound.last_reset_at = now
                changed = True
    if changed:
        db.commit()


@xray.serialized
def reconcile():
    global _certificate_reload_pending
    from app.services import wireguard, amnezia_runtime, singbox_runtime, mtproto_runtime
    with SessionLocal() as db:
        from app.services.user_lifecycle import reconcile as reconcile_users
        reconcile_users(db)
        certificates_changed = certificate_changes(db)
        wireguard.reconcile(db)
        amnezia_runtime.reconcile(db)
        reconcile_inbounds(db)
    if not settings.xray_enabled:
        singbox_runtime.stop()
        mtproto_runtime.stop()
        return
    with SessionLocal() as db:
        if not xray.xray_status()['running']:
            if Path(settings.xray_config_path).is_file() and get_setting(db, 'xray_autostart', True):
                result = xray.apply_config(db)
                if not result['ok']:
                    logger.error('Xray could not restore its validated configuration.')
                else:
                    _certificate_reload_pending = False
                    singbox_runtime.reconcile(db)
                    mtproto_runtime.reconcile(db)
            return
        xray.sync_stats(db)
        from app.services.monitoring import refresh_from_core
        refresh_from_core(db)
        config, *_ = xray.generate_config(db)
        path = Path(settings.xray_config_path)
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if certificates_changed or xray.config_hash(config) != xray.config_hash(existing):
            result = xray.apply_config(db)
            if not result["ok"]:
                logger.error("Xray reconciliation failed: %s", result["message"])
            else:
                _certificate_reload_pending = False

        singbox_runtime.reconcile(db)
        mtproto_runtime.reconcile(db)


async def run(stop: asyncio.Event):
    try:
        await asyncio.to_thread(reconcile)
    except Exception:
        logger.error('Local core startup reconciliation failed.')
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            try:
                await asyncio.to_thread(reconcile)
            except Exception:
                logger.exception("Local usage reconciliation failed")
