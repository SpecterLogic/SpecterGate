import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models import Setting


DEFAULT_SETTINGS: dict[str, Any] = {
    "panel_title": "SpecterGate",
    "panel_description": "پنل یکپارچه مدیریت پروکسی و اشتراک",
    "subscription_base_url": app_settings.subscription_base_url or "",
    "public_host": app_settings.public_host,
    "default_expiry_days": 30,
    "default_data_limit_gb": 0,
    "subscription_path_prefix": "sub",
    "support_url": "",
    "announcement": "",
    "registration_enabled": True,
}


def ensure_default_settings(db: Session) -> None:
    title = db.get(Setting, "panel_title")
    if title is not None:
        try:
            if json.loads(title.value) in {"همگرا", "Hamgara", "Hamgara Panel"}:
                title.value = json.dumps("SpecterGate")
        except (ValueError, TypeError):
            pass
    existing = {row.key for row in db.query(Setting).all()}
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.add(Setting(key=key, value=json.dumps(value, ensure_ascii=False)))
    db.commit()


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    try:
        return json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return row.value


def set_setting(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    encoded = json.dumps(value, ensure_ascii=False)
    if row is None:
        db.add(Setting(key=key, value=encoded))
    else:
        row.value = encoded


def all_settings(db: Session) -> dict[str, Any]:
    result = dict(DEFAULT_SETTINGS)
    for row in db.query(Setting).all():
        try:
            result[row.key] = json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            result[row.key] = row.value
    return result
