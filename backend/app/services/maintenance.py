"""Reconcile locally managed users and quotas without a manual Apply click."""
import asyncio
import json
import logging
from pathlib import Path

from app.config import settings
from app.database import SessionLocal
from app.services import xray
from app.services.settings import get_setting

logger = logging.getLogger(__name__)


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
    from app.services import wireguard
    with SessionLocal() as db:
        wireguard.reconcile(db)
        reconcile_inbounds(db)
    if not settings.xray_enabled:
        return
    with SessionLocal() as db:
        if not xray.xray_status()['running']:
            if Path(settings.xray_config_path).is_file() and get_setting(db, 'xray_autostart', True):
                result = xray.apply_config(db)
                if not result['ok']:
                    logger.error('Xray could not restore its validated configuration.')
            return
        xray.sync_stats(db)
        config, *_ = xray.generate_config(db)
        path = Path(settings.xray_config_path)
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if xray.config_hash(config) != xray.config_hash(existing):
            result = xray.apply_config(db)
            if not result["ok"]:
                logger.error("Xray reconciliation failed: %s", result["message"])


async def run(stop: asyncio.Event):
    try:
        await asyncio.to_thread(reconcile)
    except Exception:
        logger.error('Local core startup reconciliation failed.')
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            try:
                await asyncio.to_thread(reconcile)
            except Exception:
                logger.exception("Local usage reconciliation failed")
