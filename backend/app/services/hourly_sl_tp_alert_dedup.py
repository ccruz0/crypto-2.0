"""Dedupe policy for HOURLY SL/TP AUDIT Telegram (issue #616).

Suppress repeated digests for the same parent-id set; send when a new parent
appears or at most once per digest window (default 24h).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _default_state_path() -> str:
    return (
        os.getenv("HOURLY_SLTP_AUDIT_STATE_PATH") or "/tmp/hourly_sl_tp_audit_state.json"
    ).strip()


def parent_set_fingerprint(positions_missing: Iterable[Dict[str, Any]]) -> str:
    """Stable key from parent order_id (preferred) or symbol."""
    keys: List[str] = []
    for pos in positions_missing or []:
        if not isinstance(pos, dict):
            continue
        parent_id = pos.get("order_id") or pos.get("parent_order_id")
        symbol = pos.get("symbol") or "?"
        keys.append(f"{symbol}:{parent_id or symbol}")
    return "|".join(sorted(keys))


def _parse_iso_utc(ts: str) -> Optional[float]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


@dataclass
class HourlySlTpDedupDecision:
    send_alert: bool
    suppress_reason: str = ""
    fingerprint: str = ""


def evaluate_hourly_sl_tp_audit_send(
    state: Dict[str, Any],
    positions_missing: Iterable[Dict[str, Any]],
    *,
    now_epoch: float,
    digest_interval_hours: float = 24.0,
) -> HourlySlTpDedupDecision:
    fp = parent_set_fingerprint(positions_missing)
    if not fp:
        return HourlySlTpDedupDecision(send_alert=False, suppress_reason="empty_set")

    last_fp = (state.get("last_fingerprint") or "").strip()
    last_sent_ts = state.get("last_sent_ts") or ""
    last_sent_epoch = _parse_iso_utc(last_sent_ts)
    digest_interval_s = max(3600.0, digest_interval_hours * 3600.0)

    if fp != last_fp:
        return HourlySlTpDedupDecision(send_alert=True, fingerprint=fp)

    if last_sent_epoch is None:
        return HourlySlTpDedupDecision(send_alert=True, fingerprint=fp)

    elapsed = now_epoch - last_sent_epoch
    if elapsed >= digest_interval_s:
        return HourlySlTpDedupDecision(send_alert=True, fingerprint=fp)

    return HourlySlTpDedupDecision(
        send_alert=False,
        suppress_reason="same_parent_set_within_digest_window",
        fingerprint=fp,
    )


def load_state(path: Optional[str] = None) -> Dict[str, Any]:
    p = path or _default_state_path()
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_state(state: Dict[str, Any], path: Optional[str] = None) -> None:
    p = path or _default_state_path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(state, fh)


def record_sent(
    fingerprint: str,
    *,
    now_iso: Optional[str] = None,
    path: Optional[str] = None,
) -> None:
    ts = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_state({"last_fingerprint": fingerprint, "last_sent_ts": ts}, path=path)
