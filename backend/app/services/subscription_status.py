"""Importable, nonfunctional status row for subscription clients such as v2rayNG."""
import math
from datetime import datetime, timezone
from urllib.parse import quote


def title(target):
    status = target.status
    if status in {"expired", "limited"}:
        reason = "پایان زمان" if status == "expired" else "پایان حجم"
        return f"⛔ اشتراک شما به پایان رسید | {reason}"
    if status != "active":
        return "⛔ اشتراک شما غیرفعال است"
    quotas = [target]
    group = getattr(target, "subscription", None)
    if group is not None:
        quotas.append(group)
    expires = [q.expire_at.replace(tzinfo=timezone.utc) if q.expire_at.tzinfo is None else q.expire_at for q in quotas if q.expire_at]
    days = max(0, math.ceil((min(expires) - datetime.now(timezone.utc)).total_seconds() / 86400)) if expires else None
    remains = [max(0, q.data_limit_bytes - q.used_traffic_bytes) for q in quotas if q.data_limit_bytes is not None]
    remaining = min(remains) if remains else None
    volume = f"{remaining / 1024**3:.2f} GiB" if remaining is not None else "نامحدود"
    duration = f"{days} روز" if days is not None else "نامحدود"
    return f"ℹ️ باقی‌مانده: {duration} | حجم: {volume}"


def record(target):
    remark = title(target)
    # No credential or real server endpoint: selecting this row cannot grant access.
    return {"remark": remark, "protocol": "vless", "uri": "vless://00000000-0000-4000-8000-000000000000@127.0.0.1:9?encryption=none&security=none&type=tcp#" + quote(remark)}
