"""Encrypt integration secrets with a separate, installation-local master key."""
import base64
import os
import threading
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.models import ProtectedSetting

KEY_PATH = BASE_DIR / "data" / "secrets.key"
_key_lock = threading.Lock()


def _read_or_create_key() -> bytes:
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(AESGCM.generate_key(bit_length=256))
    key = KEY_PATH.read_bytes()
    if len(key) != 32:
        raise RuntimeError("Invalid integration master key; restore the installation key.")
    return key


def master_key() -> bytes:
    with _key_lock:
        return _read_or_create_key()


def put_secret(db: Session, name: str, value: str):
    nonce = os.urandom(12)
    encrypted = AESGCM(master_key()).encrypt(nonce, value.encode(), name.encode())
    row = db.get(ProtectedSetting, name)
    if row is None:
        row = ProtectedSetting(key=name)
        db.add(row)
    row.ciphertext = base64.b64encode(nonce + encrypted).decode()


def get_secret(db: Session, name: str) -> str | None:
    row = db.get(ProtectedSetting, name)
    if row is None:
        return None
    try:
        payload = base64.b64decode(row.ciphertext, validate=True)
        return AESGCM(master_key()).decrypt(payload[:12], payload[12:], name.encode()).decode()
    except Exception as exc:
        raise RuntimeError("Cannot decrypt integration secret; check the installation master key.") from None


def has_secret(db: Session, name: str) -> bool:
    return db.get(ProtectedSetting, name) is not None
