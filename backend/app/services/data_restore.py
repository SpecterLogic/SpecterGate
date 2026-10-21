"""Portable data snapshots and transactional owner-initiated restoration.

Administrator accounts, sessions, bot credentials and deployment URLs are preserved.
Archives are read without extracting paths or executing SQL from uploaded files.
"""
import base64
import io
import json
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import DateTime, JSON, Boolean, select

from app.database import Base
from app.models import Admin, ProtectedSetting, Setting
from app.services import vault
from app.services.backup_crypto import decrypt_archive

TABLES = ("plans", "nodes", "inbounds", "dns_tunnels", "subscription_groups", "vpn_users", "tunnel_gateway_settings", "user_resource_access", "group_resource_access", "wireguard_peers", "amnezia_peers", "user_devices")
MAX_UPLOAD = 16 * 1024 * 1024


def portable_setting(key):
    return key.startswith(("routing_", "dns_config_")) or key == "amneziawg_params"


def export_data(connection):
    tables = {}
    for name in TABLES:
        tables[name] = [dict(row) for row in connection.execute(select(Base.metadata.tables[name])).mappings()]
    tables["settings"] = [dict(row) for row in connection.execute(select(Setting.__table__)).mappings() if portable_setting(row["key"])]
    tables["protected_settings"] = [dict(row) for row in connection.execute(select(ProtectedSetting.__table__)).mappings() if row["key"].startswith(("warp_private_", "wireguard_peer_", "proxy_password_", "amnezia_peer_", "ssh_host_key"))]
    names = {str(row.id): row.username for row in connection.execute(select(Admin.id, Admin.username))}
    return json.dumps({"format": "spectergate-data", "version": 1, "admins": names, "tables": tables}, default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value), ensure_ascii=False).encode()


def _legacy_sqlite(payload):
    with tempfile.TemporaryDirectory(prefix="sg-restore-read-") as directory:
        file = Path(directory) / "snapshot.db"
        file.write_bytes(payload)
        with sqlite3.connect(f"file:{file.as_posix()}?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.row_factory = sqlite3.Row
            actual = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            tables = {}
            for name in (*TABLES, "settings", "protected_settings"):
                rows = [dict(row) for row in connection.execute(f'SELECT * FROM "{name}" LIMIT 100001')] if name in actual else []
                if name == "settings": rows = [r for r in rows if portable_setting(r["key"])]
                if name == "protected_settings": rows = [r for r in rows if r["key"].startswith(("warp_private_", "wireguard_peer_", "proxy_password_", "amnezia_peer_", "ssh_host_key"))]
                tables[name] = rows
            names = {str(row["id"]): row["username"] for row in connection.execute("SELECT id,username FROM admins")} if "admins" in actual else {}
            return {"format": "spectergate-data", "version": 1, "admins": names, "tables": tables}


def inspect(payload: bytes, password: str):
    if len(payload) > MAX_UPLOAD:
        raise ValueError("حداکثر اندازهٔ فایل بازیابی ۱۶ مگابایت است.")
    try:
        decoded = decrypt_archive(payload, password)
        files, total = {}, 0
        with tarfile.open(fileobj=io.BytesIO(decoded), mode="r|gz") as archive:
            for entry in archive:
                total += entry.size
                if not entry.isfile() or entry.size < 0 or total > 256 * 1024 * 1024:
                    raise ValueError("ساختار آرشیو معتبر نیست یا بیش از حد بزرگ است.")
                if entry.name in {"data.json", "secrets.key", "database.sqlite3", "manifest.json"}:
                    if entry.name in files: raise ValueError("Duplicate archive entry")
                    if entry.name == "data.json" and entry.size > 32 * 1024 * 1024: raise ValueError("Data snapshot too large")
                    files[entry.name] = archive.extractfile(entry).read()
        manifest = json.loads(files.get("manifest.json", b"{}"))
        if manifest.get("application") != "SpecterGate": raise ValueError("Invalid application")
        data = json.loads(files["data.json"]) if "data.json" in files else _legacy_sqlite(files["database.sqlite3"])
        if data.get("format") != "spectergate-data" or data.get("version") != 1: raise ValueError("Unsupported backup version")
        tables = data["tables"]
        tables.setdefault("user_devices", [])
        tables.setdefault("amnezia_peers", [])  # Older version-1 snapshots.
        if set(tables) - set((*TABLES, "settings", "protected_settings")): raise ValueError("Unexpected table")
        for name in TABLES:
            if name not in tables or not isinstance(tables[name], list) or len(tables[name]) > 100000: raise ValueError("Invalid table")
        for name, rows in tables.items():
            columns = Base.metadata.tables[name].columns
            for row in rows:
                if not isinstance(row, dict) or set(row) - set(columns.keys()): raise ValueError("Unexpected column")
                for field, value in list(row.items()):
                    col = columns[field]
                    if value is None:
                        if not col.nullable: raise ValueError("Missing required value")
                        continue
                    if isinstance(col.type, DateTime): row[field] = datetime.fromisoformat(value) if isinstance(value, str) else value
                    elif isinstance(col.type, JSON) and isinstance(value, str): row[field] = json.loads(value)
                    elif isinstance(col.type, Boolean):
                        if value not in (True, False, 0, 1): raise ValueError("Invalid boolean")
                        row[field] = bool(value)
                    elif getattr(col.type, "length", None) and len(str(value)) > col.type.length: raise ValueError("Value too long")
        # Authenticate selected encrypted keys before any destructive statement.
        secrets = {}
        for row in tables.get("protected_settings", []):
            name = row["key"]
            if not name.startswith(("warp_private_", "wireguard_peer_", "proxy_password_", "amnezia_peer_", "ssh_host_key")): raise ValueError("Unsupported secret")
            key = files.get("secrets.key", b"")
            raw = base64.b64decode(row["ciphertext"], validate=True)
            secrets[name] = AESGCM(key).decrypt(raw[:12], raw[12:], name.encode()).decode()
        if any(not portable_setting(r["key"]) for r in tables.get("settings", [])): raise ValueError("Unsupported setting")
        return data, secrets
    except ValueError:
        raise
    except Exception:
        raise ValueError("فایل یا رمز بکاپ نامعتبر است؛ بکاپ قدیمی PostgreSQL را با ابزار خط فرمان بازیابی کنید.") from None


def summary(data):
    return {name: len(data["tables"].get(name, [])) for name in TABLES}


def restore(db, data, secrets, owner_id):
    from app.services.wireguard import server_status
    live = server_status()
    from app.services import amnezia_runtime
    awg_live = amnezia_runtime.server_status()
    from app.schemas import InboundCreate, DnsTunnelCreate, UserCreate
    for row in data["tables"]["inbounds"]: InboundCreate.model_validate(row)
    for row in data["tables"]["dns_tunnels"]: DnsTunnelCreate.model_validate(row)
    for row in data["tables"]["vpn_users"]: UserCreate.model_validate(row)
    names = {a.username: a.id for a in db.query(Admin).all()}
    mapping = {int(old): names.get(name, owner_id) for old, name in data.get("admins", {}).items()}
    db.rollback()
    try:
        # Delete dependent historical samples first. Totals are part of the user snapshot.
        for name in ("notification_events", "traffic_samples", "node_usage_receipts", *reversed(TABLES)):
            db.execute(Base.metadata.tables[name].delete())
        for name in TABLES:
            table = Base.metadata.tables[name]
            for source in data["tables"][name]:
                row = dict(source)
                for column in ("created_by", "owner_admin_id"):
                    if column in row: row[column] = mapping.get(row[column], owner_id)
                if name in {"wireguard_peers", "amnezia_peers"}:
                    state = live if name == "wireguard_peers" else awg_live
                    sample = state.get("peers", {}).get(row["public_key"], {})
                    row.update(last_rx=int(sample.get("rx", 0)), last_tx=int(sample.get("tx", 0)), counter_epoch=state.get("epoch", ""))
                db.execute(table.insert().values(**row))
        db.execute(Setting.__table__.delete().where(Setting.key.startswith("routing_") | Setting.key.startswith("dns_config_") | (Setting.key == "amneziawg_params")))
        for row in data["tables"].get("settings", []): db.execute(Setting.__table__.insert().values(**row))
        db.execute(ProtectedSetting.__table__.delete().where(ProtectedSetting.key.startswith("warp_private_") | ProtectedSetting.key.startswith("wireguard_peer_") | ProtectedSetting.key.startswith("proxy_password_") | (ProtectedSetting.key.startswith("amnezia_peer_") | (ProtectedSetting.key == "ssh_host_key"))))
        db.expire_all()
        for name, value in secrets.items(): vault.put_secret(db, name, value)
        db.flush()
        # Reset PostgreSQL sequences after inserting preserved primary keys.
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy import text
            for name in TABLES:
                table = Base.metadata.tables[name]
                if "id" in table.columns:
                    db.execute(text(f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), COALESCE((SELECT MAX(id) FROM {name}), 1), EXISTS(SELECT 1 FROM {name}))"))
        db.commit()
    except Exception:
        db.rollback()
        raise
