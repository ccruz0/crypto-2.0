"""Tests for alert-gated order placement policy."""
from app.services.signal_order_policy import (
    resolve_legacy_buy_order_gate,
    signal_order_requires_alert,
)


def test_requires_alert_by_default(monkeypatch):
    monkeypatch.delenv("SIGNAL_ORDER_REQUIRES_ALERT", raising=False)
    assert signal_order_requires_alert() is True


def test_orchestrator_blocks_legacy_when_alert_sent(monkeypatch):
    monkeypatch.delenv("SIGNAL_ORDER_REQUIRES_ALERT", raising=False)
    should, reason = resolve_legacy_buy_order_gate(
        blocked_by_limits=False,
        buy_alert_sent_successfully=True,
    )
    assert should is False
    assert reason == "orchestrator_handled"


def test_no_order_without_alert_when_required(monkeypatch):
    monkeypatch.delenv("SIGNAL_ORDER_REQUIRES_ALERT", raising=False)
    should, reason = resolve_legacy_buy_order_gate(
        blocked_by_limits=False,
        buy_alert_sent_successfully=False,
    )
    assert should is False
    assert reason == "alert_required_not_sent"


def test_legacy_allowed_when_alert_not_required(monkeypatch):
    monkeypatch.setenv("SIGNAL_ORDER_REQUIRES_ALERT", "false")
    should, reason = resolve_legacy_buy_order_gate(
        blocked_by_limits=False,
        buy_alert_sent_successfully=False,
    )
    assert should is True
    assert reason is None


def test_limits_block_before_orchestrator_check(monkeypatch):
    monkeypatch.delenv("SIGNAL_ORDER_REQUIRES_ALERT", raising=False)
    should, reason = resolve_legacy_buy_order_gate(
        blocked_by_limits=True,
        buy_alert_sent_successfully=True,
    )
    assert should is False
    assert reason == "blocked_by_limits"
