"""Bound failed-login work for direct API deployments as well as Nginx."""
from collections import OrderedDict, deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException

_failures: OrderedDict[str, deque] = OrderedDict()
_lock = Lock()
WINDOW = 300
LIMIT = 10


def check_login(key: str) -> None:
    with _lock:
        now = monotonic()
        entries = _failures.get(key)
        if entries is None:
            return
        while entries and entries[0] <= now - WINDOW:
            entries.popleft()
        if len(entries) >= LIMIT:
            raise HTTPException(status_code=429, detail="تلاش‌های ناموفق زیاد است؛ چند دقیقه بعد دوباره تلاش کنید.", headers={"Retry-After": str(max(1, int(entries[0] + WINDOW - now)))})


def failed_login(key: str) -> None:
    with _lock:
        _failures.setdefault(key, deque(maxlen=LIMIT)).append(monotonic())
        _failures.move_to_end(key)
        while len(_failures) > 10000:
            _failures.popitem(last=False)


def successful_login(key: str) -> None:
    with _lock:
        _failures.pop(key, None)
