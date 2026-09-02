"""Alertmanager → Telegram relay throttles (issue #616).

Pure helpers so short-lived InstanceDown flaps do not ping-pong FIRING+RESOLVED.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Match Prometheus rule `for:` on InstanceDown (alerts.yml).
INSTANCE_DOWN_MIN_DURATION_S = 15 * 60


def _parse_rfc3339(ts: str) -> Optional[float]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def alert_active_duration_seconds(
    alert: Dict[str, Any],
    *,
    now_epoch: Optional[float] = None,
) -> Optional[float]:
    """Seconds between startsAt and endsAt (or now for firing)."""
    start = _parse_rfc3339(alert.get("startsAt") or "")
    if start is None:
        return None
    status = (alert.get("status") or "").lower()
    if status == "resolved":
        end = _parse_rfc3339(alert.get("endsAt") or "")
        if end is None:
            return None
        return max(0.0, end - start)
    ref = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
    return max(0.0, ref - start)


def should_suppress_instance_down_telegram(
    alert: Dict[str, Any],
    *,
    min_duration_s: int = INSTANCE_DOWN_MIN_DURATION_S,
    now_epoch: Optional[float] = None,
) -> Tuple[bool, str]:
    """Suppress InstanceDown Telegram when the outage was shorter than min_duration."""
    name = (alert.get("labels") or {}).get("alertname", "")
    if name != "InstanceDown":
        return False, ""
    duration = alert_active_duration_seconds(alert, now_epoch=now_epoch)
    if duration is None:
        return False, ""
    if duration < min_duration_s:
        status = (alert.get("status") or "unknown").upper()
        return True, f"instance_down_short_flap_{int(duration)}s"
    return False, ""


def filter_alerts_for_telegram(
    alerts: Iterable[Dict[str, Any]],
    *,
    min_instance_down_duration_s: int = INSTANCE_DOWN_MIN_DURATION_S,
    now_epoch: Optional[float] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Return alerts to send and suppression reasons for dropped ones."""
    kept: List[Dict[str, Any]] = []
    suppressed: List[str] = []
    for alert in alerts:
        suppress, reason = should_suppress_instance_down_telegram(
            alert,
            min_duration_s=min_instance_down_duration_s,
            now_epoch=now_epoch,
        )
        if suppress:
            suppressed.append(reason)
            continue
        kept.append(alert)
    return kept, suppressed
