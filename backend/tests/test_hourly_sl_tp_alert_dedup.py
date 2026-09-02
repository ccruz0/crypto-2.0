"""Tests for HOURLY SL/TP AUDIT Telegram dedupe (issue #616)."""
import time

from app.services.hourly_sl_tp_alert_dedup import (
    evaluate_hourly_sl_tp_audit_send,
    parent_set_fingerprint,
)


def test_parent_set_fingerprint_stable_and_sorted():
    rows = [
        {"symbol": "BTC_USD", "order_id": "p2"},
        {"symbol": "APT_USD", "order_id": "p1"},
    ]
    assert parent_set_fingerprint(rows) == "APT_USD:p1|BTC_USD:p2"


def test_new_parent_set_always_sends():
    now = time.time()
    state = {"last_fingerprint": "APT_USD:p1", "last_sent_ts": "2026-09-01T12:00:00Z"}
    rows = [{"symbol": "BTC_USD", "order_id": "p2"}]
    d = evaluate_hourly_sl_tp_audit_send(state, rows, now_epoch=now)
    assert d.send_alert is True
    assert d.fingerprint == "BTC_USD:p2"


def test_same_parent_set_suppressed_within_24h():
    now = time.time()
    state = {
        "last_fingerprint": "APT_USD:p1|BTC_USD:p2",
        "last_sent_ts": "2026-09-01T12:00:00Z",
    }
    rows = [
        {"symbol": "BTC_USD", "order_id": "p2"},
        {"symbol": "APT_USD", "order_id": "p1"},
    ]
    d = evaluate_hourly_sl_tp_audit_send(
        state,
        rows,
        now_epoch=time.mktime(time.strptime("2026-09-01T14:00:00", "%Y-%m-%dT%H:%M:%S")),
    )
    assert d.send_alert is False
    assert d.suppress_reason == "same_parent_set_within_digest_window"


def test_same_parent_set_allowed_after_digest_window():
    rows = [{"symbol": "BONK_USD", "order_id": "leftover"}]
    fp = parent_set_fingerprint(rows)
    state = {"last_fingerprint": fp, "last_sent_ts": "2026-09-01T00:00:00Z"}
    d = evaluate_hourly_sl_tp_audit_send(
        state,
        rows,
        now_epoch=time.mktime(time.strptime("2026-09-02T01:00:00", "%Y-%m-%dT%H:%M:%S")),
        digest_interval_hours=24.0,
    )
    assert d.send_alert is True
