"""Tests for Alertmanager InstanceDown Telegram throttle (issue #616)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

TG_ALERTS = (
    Path(__file__).resolve().parents[2] / "scripts/aws/observability/telegram-alerts"
)
sys.path.insert(0, str(TG_ALERTS))

from throttle import (  # noqa: E402
    filter_alerts_for_telegram,
    should_suppress_instance_down_telegram,
)


def _epoch(iso: str) -> float:
    s = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()


def _alert(status: str, *, starts: str, ends: str = "") -> dict:
    payload = {
        "status": status,
        "startsAt": starts,
        "labels": {"alertname": "InstanceDown", "job": "backend", "severity": "critical"},
        "annotations": {"summary": "down", "description": "down"},
    }
    if ends:
        payload["endsAt"] = ends
    return payload


def test_suppress_short_firing_instance_down():
    suppress, reason = should_suppress_instance_down_telegram(
        _alert("firing", starts="2026-09-01T12:00:00Z"),
        min_duration_s=900,
        now_epoch=_epoch("2026-09-01T12:05:00Z"),
    )
    assert suppress is True
    assert reason.startswith("instance_down_short_flap_")


def test_allow_sustained_firing_instance_down():
    suppress, _ = should_suppress_instance_down_telegram(
        _alert("firing", starts="2026-09-01T12:00:00Z"),
        min_duration_s=900,
        now_epoch=_epoch("2026-09-01T12:20:00Z"),
    )
    assert suppress is False


def test_suppress_short_resolved_instance_down():
    suppress, reason = should_suppress_instance_down_telegram(
        _alert(
            "resolved",
            starts="2026-09-01T12:00:00Z",
            ends="2026-09-01T12:05:00Z",
        ),
        min_duration_s=900,
    )
    assert suppress is True
    assert "300s" in reason


def test_other_alerts_not_suppressed():
    alert = {
        "status": "firing",
        "startsAt": "2026-09-01T12:00:00Z",
        "labels": {"alertname": "BackendHigh5xxRate"},
    }
    suppress, reason = should_suppress_instance_down_telegram(alert)
    assert suppress is False
    assert reason == ""


def test_filter_drops_short_flap_batch():
    alerts = [
        _alert(
            "resolved",
            starts="2026-09-01T12:00:00Z",
            ends="2026-09-01T12:04:00Z",
        ),
        {
            "status": "firing",
            "startsAt": "2026-09-01T12:00:00Z",
            "labels": {"alertname": "HostMemoryCritical"},
        },
    ]
    kept, suppressed = filter_alerts_for_telegram(alerts, min_instance_down_duration_s=900)
    assert len(kept) == 1
    assert kept[0]["labels"]["alertname"] == "HostMemoryCritical"
    assert suppressed
