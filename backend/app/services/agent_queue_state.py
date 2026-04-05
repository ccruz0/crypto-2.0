"""In-memory deduplication for anomaly-classified tasks (scheduler / prepare path).

Bounded window prevents repeated pickup of the same anomaly content within
``ANOMALY_DEDUP_WINDOW_SECONDS`` (default 1800). Prune expired entries each cycle.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_store: dict[str, float] = {}

_ANOMALY_DEDUP_WINDOW_S = int(os.getenv("ANOMALY_DEDUP_WINDOW_SECONDS", "1800"))


def _fingerprint(raw_task: dict[str, Any]) -> str:
    title = str((raw_task or {}).get("task") or "")
    details = str((raw_task or {}).get("details") or "")
    body = f"{title}|{details}"
    return hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()[:48]


def prune_anomaly_dedup() -> None:
    """Remove entries older than the dedup window."""
    now = time.time()
    cutoff = now - _ANOMALY_DEDUP_WINDOW_S
    dead = [k for k, ts in _store.items() if ts < cutoff]
    for k in dead:
        del _store[k]


def should_skip_duplicate_anomaly(raw_task: dict[str, Any]) -> bool:
    """True if the same title+details hash was seen within the dedup window."""
    fp = _fingerprint(raw_task)
    now = time.time()
    ts = _store.get(fp)
    if ts is not None and (now - ts) < _ANOMALY_DEDUP_WINDOW_S:
        return True
    return False


def record_anomaly_processed(raw_task: dict[str, Any]) -> None:
    """Record that we claimed/started processing this anomaly fingerprint."""
    _store[_fingerprint(raw_task)] = time.time()
