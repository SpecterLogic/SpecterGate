"""Persisted rolling traffic cycles and bounded account renewals."""
from datetime import datetime, timedelta, timezone
from app.models import VPNUser, as_utc


def reconcile(db, now=None):
    now = now or datetime.now(timezone.utc)
    for user in db.query(VPNUser).with_for_update().all():
        if user.traffic_reset_days:
            interval = timedelta(days=user.traffic_reset_days)
            anchor = as_utc(user.traffic_reset_at) or as_utc(user.created_at) or now
            periods = int((now - anchor) // interval)
            if periods > 0:
                user.upload_bytes = user.download_bytes = 0
                user.traffic_reset_at = anchor + periods * interval
                from app.services.notifications import enqueue
                enqueue(db, f"reset:{user.id}:{user.traffic_reset_at.isoformat()}", "Traffic cycle reset", f"Traffic cycle reset for {user.username}.")
        expiry = as_utc(user.expire_at)
        if user.is_active and expiry and expiry <= now and user.renewal_days and user.renewal_remaining > 0:
            # One purchased/authorized renewal is consumed, even after downtime.
            user.expire_at = now + timedelta(days=user.renewal_days)
            user.renewal_remaining -= 1
            user.upload_bytes = user.download_bytes = 0
            user.traffic_reset_at = now
            from app.services.notifications import enqueue
            enqueue(db, f"renew:{user.id}:{expiry.isoformat()}", "Account renewed", f"Account {user.username} renewed; {user.renewal_remaining} renewals remain.")
        state = user.status
        if user.last_notified_status and state != user.last_notified_status and state in {"limited", "expired", "disabled"}:
            from app.services.notifications import enqueue
            enqueue(db, f"state:{user.id}:{state}:{now.isoformat()}", "Account status changed", f"Account {user.username}: {state}.")
        user.last_notified_status = state
    db.commit()
