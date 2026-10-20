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


@xray.serialized
def reconcile():
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
