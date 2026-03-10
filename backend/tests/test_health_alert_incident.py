"""Tests for health alert incident dedupe and remediation policy."""
import time
import pytest
from app.services.health_alert_incident import (
    is_market_data_incident,
    incident_fingerprint,
    evaluate_after_snapshot,
    merge_state,
    default_state,
)


def test_is_market_data_incident_verify_label():
    assert is_market_data_incident("FAIL:MARKET_DATA:FAIL") is True
    assert is_market_data_incident("FAIL:MARKET_UPDATER:FAIL") is True
    assert is_market_data_incident("FAIL:API_HEALTH:missing") is False


def test_is_market_data_incident_status_pair():
    assert is_market_data_incident("other", "FAIL", "FAIL") is True
    assert is_market_data_incident("other", "PASS", "FAIL") is False


def test_fingerprint_stable():
    fp1 = incident_fingerprint("FAIL:MARKET_DATA:FAIL", "FAIL", "FAIL")
    fp2 = incident_fingerprint("FAIL:MARKET_DATA:FAIL", "FAIL", "FAIL")
    assert fp1 == fp2
    assert fp1 != incident_fingerprint("FAIL:API_HEALTH:x", "FAIL", "FAIL")


def test_recovery_sends_resolved_once():
    now = time.time()
    state = merge_state(
        default_state(),
        incident_open=True,
        incident_fingerprint="fp1",
        last_sent_ts="2020-01-01T00:00:00Z",
    )
    d = evaluate_after_snapshot(
        state,
        triggered=True,
        severity_ok=True,
        verify_label="PASS",
        market_data_status="PASS",
        market_updater_status="PASS",
        streak=0,
        reason="",
        now_epoch=now,
        cooldown_mins=30,
        grace_mins_after_remediation=2,
        max_remediation_attempts=3,
        escalation_cooldown_mins=60,
    )
    assert d.send_resolved_alert is True
    assert d.send_fail_alert is False


def test_same_incident_streak_growth_does_not_resend():
    """Root cause fix: streak 3->4 must not bypass cooldown for same incident."""
    now = time.time()
    state = merge_state(
        default_state(),
        incident_open=True,
        incident_fingerprint=incident_fingerprint("FAIL:MARKET_DATA:FAIL", "FAIL", "FAIL"),
        last_sent_ts="2026-03-10T12:00:00Z",  # now is shortly after
        last_reason="streak_fail_3 (streak=3)",
        remediation_attempts=1,
        last_escalation_ts="2026-03-10T12:00:00Z",
    )
    # Simulate same minute bucket - cooldown blocks
    d = evaluate_after_snapshot(
        state,
        triggered=True,
        severity_ok=False,
        verify_label="FAIL:MARKET_DATA:FAIL",
        market_data_status="FAIL",
        market_updater_status="FAIL",
        streak=5,
        reason="streak_fail_3 (streak=5)",
        now_epoch=parse_epoch("2026-03-10T12:02:00Z"),
        cooldown_mins=30,
        grace_mins_after_remediation=0,
        max_remediation_attempts=3,
        escalation_cooldown_mins=60,
    )
    assert d.send_fail_alert is False
    assert "dedupe" in d.suppress_reason or d.suppress_reason == "incident_open_cooldown_no_streak_bypass"


def parse_epoch(ts: str) -> float:
    from app.services.health_alert_incident import parse_iso_utc
    return parse_iso_utc(ts) or 0.0


def test_first_market_failure_allows_remediation_then_escalation():
    now = parse_epoch("2026-03-10T12:00:00Z")
    state = default_state()
    d = evaluate_after_snapshot(
        state,
        triggered=True,
        severity_ok=False,
        verify_label="FAIL:MARKET_DATA:FAIL",
        market_data_status="FAIL",
        market_updater_status="FAIL",
        streak=3,
        reason="streak_fail_3 (streak=3)",
        now_epoch=now,
        cooldown_mins=30,
        grace_mins_after_remediation=0,
        max_remediation_attempts=3,
        escalation_cooldown_mins=60,
    )
    # No incident open yet -> caller will remediate first; if still fail, send_fail can be true
    assert d.send_resolved_alert is False


def test_grace_after_remediation_suppresses():
    now = parse_epoch("2026-03-10T12:01:00Z")
    state = merge_state(
        default_state(),
        incident_open=True,
        last_remediation_ts="2026-03-10T12:00:30Z",
        incident_fingerprint=incident_fingerprint("FAIL:MARKET_DATA:FAIL", "FAIL", "FAIL"),
    )
    d = evaluate_after_snapshot(
        state,
        triggered=True,
        severity_ok=False,
        verify_label="FAIL:MARKET_DATA:FAIL",
        market_data_status="FAIL",
        market_updater_status="FAIL",
        streak=3,
        reason="streak_fail_3",
        now_epoch=now,
        cooldown_mins=30,
        grace_mins_after_remediation=3,
        max_remediation_attempts=3,
        escalation_cooldown_mins=60,
    )
    assert d.send_fail_alert is False
    assert d.suppress_reason == "grace_after_remediation"
