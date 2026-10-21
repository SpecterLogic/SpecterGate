"""Encrypted TOTP state and atomic one-time recovery/code consumption."""
import hashlib
import hmac
import json
import time
import secrets

from sqlalchemy import update

from app.models import Admin, AdminSession, ProtectedSetting
from app.services import vault
from app.services.totp import get_totp_token


def code_hash(admin_id, code):
    normalized = code.strip().upper().replace("-", "")
    return "hmac:" + hmac.new(vault.master_key(), f"recovery:{admin_id}:{normalized}".encode(), hashlib.sha256).hexdigest()


def migrate(db):
    for admin in db.query(Admin).filter(Admin.totp_enabled.is_(True)).all():
        if admin.totp_secret and not admin.totp_secret.startswith("vault:"):
            vault.put_secret(db, f"totp_{admin.id}", admin.totp_secret)
            admin.totp_secret = f"vault:{admin.id}"
            db.query(AdminSession).filter(AdminSession.admin_id == admin.id).delete()
        codes = json.loads(admin.recovery_codes_json or "[]")
        admin.recovery_codes_json = json.dumps([code if code.startswith(("hmac:", "state:")) else code_hash(admin.id, code) for code in codes])
    db.commit()


def consume(db, admin, code):
    """CAS on the stored recovery list serializes both OTP and recovery use."""
    old = admin.recovery_codes_json
    codes = json.loads(old or "[]")
    hashed = code_hash(admin.id, code)
    secret = vault.get_secret(db, f"totp_{admin.id}") if (admin.totp_secret or "").startswith("vault:") else admin.totp_secret
    step_name = f"totp_step_{admin.id}"
    previous = int(vault.get_secret(db, step_name) or "-1")
    step = int(time.time()) // 30
    matched_step = None
    if secret and len(code.strip()) == 6 and code.strip().isascii() and code.strip().isdigit():
        for candidate in (step - 1, step, step + 1):
            try:
                expected = get_totp_token(secret, for_time=candidate * 30)
            except ValueError:
                break
            if candidate > previous and hmac.compare_digest(expected, code.strip()):
                matched_step = candidate
                break
    if matched_step is None:
        match = next((item for item in codes if hmac.compare_digest(item, hashed)), None)
        if match is None:
            return False
        codes.remove(match)
    # Include a nonce so even OTP logins (without recovery changes) acquire a
    # unique CAS state; only hmac-prefixed elements represent recovery codes.
    codes = [item for item in codes if item.startswith("hmac:")]
    codes.append("state:" + secrets.token_hex(16))
    changed = db.execute(update(Admin).where(Admin.id == admin.id, Admin.recovery_codes_json == old).values(recovery_codes_json=json.dumps(codes)), execution_options={"synchronize_session": False})
    if changed.rowcount != 1:
        db.rollback()
        return False
    if matched_step is not None:
        vault.put_secret(db, step_name, str(matched_step))
    db.commit()
    db.refresh(admin)
    return True


def clear(db, admin):
    for name in (f"totp_{admin.id}", f"totp_step_{admin.id}", f"totp_pending_{admin.id}"):
        row = db.get(ProtectedSetting, name)
        if row:
            db.delete(row)
