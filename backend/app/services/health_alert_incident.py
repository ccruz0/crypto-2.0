"""
Health alert incident state and dedupe policy for ATP health_snapshot_telegram_alert flow.

Used to:
- Detect MARKET_DATA / market_updater failures from verify_label and snapshot fields
- Decide whether to suppress repeated Telegram alerts during an open incident
- Decide when to send escalation after cooldown / max attempts
- Decide when to send a single resolved message after recovery

State is stored in JSON on disk by the shell script; this module provides pure logic
so behavior can be unit-tested without bash.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


def parse_iso_utc(ts: str) -> Optional[float]:
    """Parse ISO timestamp to epoch seconds; None if invalid."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def is_market_data_incident(
    verify_label: str,
    market_data_status: str = "",
    market_updater_status: str = "",
) -> bool:
    """
    True if this failure is the market data / updater class that we can remediate
    by restarting market-updater-aws and related steps.
    """
    v = (verify_label or "").upper()
    if "MARKET_DATA" in v or "MARKET_UPDATER" in v:
        return True
    md = (market_data_status or "").upper()
    mu = (market_updater_status or "").upper()
    if md == "FAIL" and mu == "FAIL":
        return True
    if "FAIL:MARKET_DATA" in v:
        return True
    return False


def incident_fingerprint(
    verify_label: str,
    market_data_status: str = "",
    market_updater_status: str = "",
) -> str:
    """Stable key for dedupe: same incident while these remain failing together."""
    return "|".join(
        [
            (verify_label or "unknown")[:120],
            (market_data_status or "").upper(),
            (market_updater_status or "").upper(),
        ]
    )


@dataclass
class IncidentDecision:
    """Result of policy evaluation."""

    send_fail_alert: bool = False
    send_resolved_alert: bool = False
    suppress_reason: str = ""
    remediation_allowed: bool = True
    log_event: str = ""


def _epoch_minutes_ago(epoch_now: float, ts_str: str) -> float:
    t = parse_iso_utc(ts_str)
    if t is None:
        return 999999.0
    return max(0.0, (epoch_now - t) / 60.0)


def evaluate_after_snapshot(
    state: Dict[str, Any],
    *,
    triggered: bool,
    severity_ok: bool,
    verify_label: str,
    market_data_status: str,
    market_updater_status: str,
    streak: int,
    reason: str,
    now_epoch: float,
    cooldown_mins: int,
    grace_mins_after_remediation: float,
    max_remediation_attempts: int,
    escalation_cooldown_mins: int,
) -> IncidentDecision:
    """
    Decide what to do this cycle given current snapshot and persisted state.

    - If severity is OK and we had an open incident -> send resolved once, clear incident.
    - If triggered and market incident -> remediation_allowed; fail alert suppressed until
      escalation_cooldown after last escalation or after max attempts cap.
    - Repeated streak growth must NOT automatically resend (fix for streak > last_streak bypass).
    """
    out = IncidentDecision()
    fp = incident_fingerprint(verify_label, market_data_status, market_updater_status)
    market_incident = is_market_data_incident(
        verify_label, market_data_status, market_updater_status
    )
    incident_open = bool(state.get("incident_open"))
    state_fp = state.get("incident_fingerprint") or ""
    attempts = int(state.get("remediation_attempts") or 0)
    last_escalation_ts = state.get("last_escalation_ts") or ""
    last_remediation_ts = state.get("last_remediation_ts") or ""

    # Recovery path: was failing, now OK
    if severity_ok and incident_open:
        out.send_resolved_alert = True
        out.log_event = "incident_resolved"
        return out

    if not triggered:
        out.suppress_reason = "rule_not_triggered"
        return out

    # First time in failure for this fingerprint -> allow alert after remediation attempt
    # (caller runs remediation before calling again with post-verify; first call may set state only)
    if not market_incident:
        # Non-market incident: use simple cooldown only, no remediation gate
        mins_since_sent = _epoch_minutes_ago(now_epoch, state.get("last_sent_ts") or "")
        if mins_since_sent < cooldown_mins:
            # Do not bypass just because streak grew
            if reason == (state.get("last_reason") or ""):
                out.suppress_reason = "cooldown_same_reason"
                return out
        out.send_fail_alert = True
        out.log_event = "escalation_non_market"
        return out

    # Market incident: one alert per incident (action_alert_sent)
    if incident_open and state_fp == fp:
        if state.get("action_alert_sent"):
            out.suppress_reason = "action_alert_already_sent"
            out.remediation_allowed = attempts < max_remediation_attempts
            out.log_event = "dedupe_suppression_hit"
            return out
        # Same incident, within cooldown, streak increased -> suppress (no escalation resend)
        mins_since_sent = _epoch_minutes_ago(now_epoch, state.get("last_sent_ts") or "")
        if mins_since_sent < cooldown_mins:
            out.suppress_reason = "incident_open_cooldown_no_streak_bypass"
            out.log_event = "dedupe_suppression_hit"
            return out

    # Grace after remediation: suppress fail alert briefly
    if last_remediation_ts:
        if _epoch_minutes_ago(now_epoch, last_remediation_ts) < grace_mins_after_remediation:
            out.suppress_reason = "grace_after_remediation"
            out.log_event = "dedupe_suppression_hit"
            return out

    out.send_fail_alert = True
    out.log_event = "escalation_or_initial_fail"
    return out


def merge_state(
    state: Dict[str, Any],
    *,
    incident_open: Optional[bool] = None,
    incident_fingerprint: Optional[str] = None,
    remediation_attempts: Optional[int] = None,
    last_remediation_ts: Optional[str] = None,
    last_escalation_ts: Optional[str] = None,
    last_sent_ts: Optional[str] = None,
    last_reason: Optional[str] = None,
    last_streak: Optional[int] = None,
    first_fail_ts: Optional[str] = None,
    action_alert_sent: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return updated state dict (copy)."""
    s = dict(state)
    if incident_open is not None:
        s["incident_open"] = incident_open
    if incident_fingerprint is not None:
        s["incident_fingerprint"] = incident_fingerprint
    if remediation_attempts is not None:
        s["remediation_attempts"] = remediation_attempts
    if last_remediation_ts is not None:
        s["last_remediation_ts"] = last_remediation_ts
    if last_escalation_ts is not None:
        s["last_escalation_ts"] = last_escalation_ts
    if last_sent_ts is not None:
        s["last_sent_ts"] = last_sent_ts
    if last_reason is not None:
        s["last_reason"] = last_reason
    if last_streak is not None:
        s["last_streak"] = last_streak
    if first_fail_ts is not None:
        s["first_fail_ts"] = first_fail_ts
    if action_alert_sent is not None:
        s["action_alert_sent"] = action_alert_sent
    return s


def default_state() -> Dict[str, Any]:
    return {
        "last_sent_ts": "",
        "last_reason": "",
        "last_streak": 0,
        "incident_open": False,
        "incident_fingerprint": "",
        "remediation_attempts": 0,
        "last_remediation_ts": "",
        "last_escalation_ts": "",
        "first_fail_ts": "",
        "action_alert_sent": False,
    }
