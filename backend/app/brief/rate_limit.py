"""In-process rate limit for brief endpoints (shared by all /api/brief/* routes)."""

from __future__ import annotations

import os
import threading
import time
from collections import deque

from fastapi import HTTPException

_lock = threading.Lock()
_hits: deque[float] = deque()


def _limit_per_minute() -> int:
    raw = (os.getenv("BRIEF_RATE_LIMIT_PER_MINUTE") or "30").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 30


def enforce_brief_rate_limit() -> None:
    """Raise 429 when the shared brief window is exceeded."""
    limit = _limit_per_minute()
    now = time.monotonic()
    window = 60.0
    with _lock:
        while _hits and (now - _hits[0]) > window:
            _hits.popleft()
        if len(_hits) >= limit:
            raise HTTPException(status_code=429, detail="rate_limited")
        _hits.append(now)


def reset_brief_rate_limit_for_tests() -> None:
    with _lock:
        _hits.clear()
