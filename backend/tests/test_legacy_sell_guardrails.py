"""Tests for legacy SELL path trading guardrails."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.signal_monitor import SignalMonitorService


def _watchlist(trade_enabled=True, amount=100.0):
    return SimpleNamespace(
        symbol="ETH_USDT",
        trade_enabled=trade_enabled,
        trade_amount_usd=amount,
        trade_on_margin=False,
    )


class TestLegacySellGuardrails:
    @patch("app.services.signal_monitor._emit_lifecycle_event")
    @patch("app.services.signal_monitor.telegram_notifier")
    @patch("app.services.signal_monitor.trade_client")
    @patch("app.utils.trading_guardrails.can_place_real_order")
    def test_legacy_sell_blocked_by_max_open_orders(
        self, mock_guard, _trade_client, _telegram, _emit
    ):
        mock_guard.return_value = (
            False,
            "blocked: MAX_OPEN_ORDERS_TOTAL limit reached (33/10)",
        )
        svc = SignalMonitorService()
        svc._telegram_send_enabled = MagicMock(return_value=False)
        db = MagicMock()

        import asyncio

        result = asyncio.run(
            svc._create_sell_order_impl(db, _watchlist(), current_price=1800.0, res_up=0.0, res_down=0.0)
        )

        assert result["blocked"] is True
        assert "MAX_OPEN_ORDERS_TOTAL" in result["message"]
        mock_guard.assert_called_once()
        assert mock_guard.call_args.kwargs["side"] == "SELL"
