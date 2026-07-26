"""Live Telegram signals must not fire when trade criteria block order placement."""
from unittest.mock import MagicMock, patch

from app.services.signal_monitor import SignalMonitorService


def test_persist_only_when_trade_enabled_and_guardrail_blocks():
    svc = SignalMonitorService()
    db = MagicMock()
    item = MagicMock(trade_enabled=True, trade_amount_usd=10.0)

    with patch.object(
        svc,
        "_orchestrator_order_guard",
        return_value=(False, "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (41/40)"),
    ):
        persist_only, reason = svc._should_persist_only_signal_alert(
            db, "DOGE_USD", "SELL", item
        )

    assert persist_only is True
    assert "MAX_OPEN_ORDERS_TOTAL" in (reason or "")


def test_live_telegram_allowed_when_guardrails_pass():
    svc = SignalMonitorService()
    db = MagicMock()
    item = MagicMock(trade_enabled=True, trade_amount_usd=10.0)

    with patch.object(svc, "_orchestrator_order_guard", return_value=(True, None)):
        persist_only, reason = svc._should_persist_only_signal_alert(
            db, "DOGE_USD", "SELL", item
        )

    assert persist_only is False
    assert reason is None


def test_alert_only_symbol_still_gets_live_telegram():
    """trade_enabled=False → alerts are informational; do not require orderability."""
    svc = SignalMonitorService()
    db = MagicMock()
    item = MagicMock(trade_enabled=False, trade_amount_usd=10.0)

    with patch.object(
        svc,
        "_orchestrator_order_guard",
        return_value=(False, "blocked: MAX_OPEN_ORDERS_TOTAL"),
    ) as guard:
        persist_only, reason = svc._should_persist_only_signal_alert(
            db, "DOGE_USD", "SELL", item
        )

    assert persist_only is False
    assert reason is None
    guard.assert_not_called()


def test_extra_block_reason_forces_persist_only():
    svc = SignalMonitorService()
    db = MagicMock()
    item = MagicMock(trade_enabled=True, trade_amount_usd=10.0)

    persist_only, reason = svc._should_persist_only_signal_alert(
        db,
        "ETH_USD",
        "BUY",
        item,
        extra_block_reason="PORTFOLIO_LIMIT",
    )

    assert persist_only is True
    assert reason == "PORTFOLIO_LIMIT"
