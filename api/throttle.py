"""In-memory sign-in throttling, following the OWASP Authentication Cheat Sheet.

Failed sign-ins are counted per account identifier (not per IP, so rotating addresses does not help) and
the same counter applies to emails that do not exist, so a lockout does not reveal which accounts are real.
After THRESHOLD failures inside WINDOW seconds the identifier is locked for LOCK seconds. A per-IP limit
covers sign-in attempts spread over many accounts and bulk registration.

ponytail: state lives in this process. It resets on restart and is not shared between workers, which is
fine for a git-clone install or one worker. Move it to the database or Redis before running several workers.
"""
from __future__ import annotations

import threading
import time

THRESHOLD = 5
WINDOW = 15 * 60
LOCK = 15 * 60
IP_LOGIN_LIMIT = 60          # sign-in attempts per IP per WINDOW
IP_REGISTER_LIMIT = 10       # new accounts per IP per hour
REGISTER_WINDOW = 60 * 60

_now = time.monotonic        # replaced in tests
_lock = threading.Lock()
_failures: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}
_hits: dict[tuple[str, str], list[float]] = {}


def reset() -> None:
    with _lock:
        _failures.clear(); _locked_until.clear(); _hits.clear()


def locked_for(identifier: str) -> int:
    """Seconds left on a lockout, 0 when the identifier may try."""
    with _lock:
        left = _locked_until.get(identifier, 0) - _now()
        if left <= 0:
            _locked_until.pop(identifier, None)
            return 0
        return int(left) + 1


def record_failure(identifier: str) -> bool:
    """Count a failed sign-in. Returns True when this failure locked the identifier."""
    now = _now()
    with _lock:
        recent = [t for t in _failures.get(identifier, []) if now - t < WINDOW] + [now]
        _failures[identifier] = recent
        if len(recent) >= THRESHOLD:
            _locked_until[identifier] = now + LOCK
            _failures.pop(identifier, None)
            return True
        return False


def record_success(identifier: str) -> None:
    with _lock:
        _failures.pop(identifier, None)
        _locked_until.pop(identifier, None)


def too_many_from(ip: str, bucket: str, limit: int, window: int) -> int:
    """Record one hit for this IP and bucket. Returns seconds to wait if the limit is exceeded, else 0."""
    now = _now()
    with _lock:
        recent = [t for t in _hits.get((bucket, ip), []) if now - t < window]
        if len(recent) >= limit:
            _hits[(bucket, ip)] = recent
            return int(window - (now - recent[0])) + 1
        recent.append(now)
        _hits[(bucket, ip)] = recent
        return 0
