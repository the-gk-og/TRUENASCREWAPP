"""
services/security/throttle.py
=============================
Small in-memory failure throttle for login-style endpoints.

State is per-process (gunicorn runs 2 workers), so the effective limit is
roughly limit x workers. That is still enough to stop online guessing; use
Redis-backed Flask-Limiter if you ever need exact cross-process counts.
"""
import threading
import time
from collections import defaultdict, deque

from flask import request

_lock = threading.Lock()
_failures: dict[tuple[str, str], deque] = defaultdict(deque)


def client_ip() -> str:
    """Client address as resolved by ProxyFix (not a raw, spoofable header)."""
    return request.remote_addr or 'unknown'


def _prune(q: deque, window: int, now: float) -> None:
    while q and now - q[0] > window:
        q.popleft()


def is_blocked(bucket: str, key: str, limit: int, window: int) -> bool:
    """True if *key* already has >= *limit* recorded failures in the last *window* seconds."""
    now = time.monotonic()
    with _lock:
        q = _failures[(bucket, key)]
        _prune(q, window, now)
        return len(q) >= limit


def record_failure(bucket: str, key: str, window: int = 900) -> None:
    now = time.monotonic()
    with _lock:
        q = _failures[(bucket, key)]
        _prune(q, window, now)
        q.append(now)
        if len(_failures) > 20000:          # keep memory bounded
            for k in [k for k, v in _failures.items() if not v][:5000]:
                _failures.pop(k, None)


def reset(bucket: str, key: str) -> None:
    with _lock:
        _failures.pop((bucket, key), None)
