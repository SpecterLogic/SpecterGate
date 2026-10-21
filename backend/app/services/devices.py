"""Client-supplied subscription HWID registration; never stores raw identifiers."""
import hashlib
import hmac
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import update
from app.models import VPNUser, UserDevice


def enforce(db, users, request):
    limited = sorted((u for u in users if u.hwid_limit), key=lambda u: u.id)
    if not limited:
        return
    hwid = request.headers.get("x-hwid", "").strip()
    if not 8 <= len(hwid) <= 256 or any(ord(c) < 32 for c in hwid):
        raise HTTPException(403, "A compatible client must send its X-HWID header for this subscription.")
    try:
        for user in limited:
            # A write locks this user on SQLite too; concurrent fetches cannot
            # both consume the final slot. One transaction covers group members.
            db.execute(update(VPNUser).where(VPNUser.id == user.id).values(hwid_limit=VPNUser.hwid_limit))
            db.refresh(user)
            if not user.hwid_limit:
                continue
            fingerprint = hmac.new(user.password.encode(), hwid.encode(), hashlib.sha256).hexdigest()
            existing = db.query(UserDevice).filter_by(user_id=user.id, fingerprint=fingerprint).first()
            if existing:
                existing.last_seen_at = datetime.now(timezone.utc)
            else:
                if db.query(UserDevice).filter_by(user_id=user.id).count() >= user.hwid_limit:
                    raise HTTPException(403, "Registered device limit reached. Ask your administrator to remove an old device.")
                label = request.headers.get("x-device-model") or request.headers.get("user-agent", "Client")
                db.add(UserDevice(user_id=user.id, fingerprint=fingerprint, label="".join(c for c in label if ord(c) >= 32)[:100]))
                db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
