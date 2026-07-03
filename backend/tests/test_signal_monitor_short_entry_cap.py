"""Integration tests: the SYSTEM_CORE position cap is enforced on the orchestrator SELL path
for SHORT ENTRIES only.

Companion to the cap-race dedup fix. Before this change ``_place_order_from_signal`` enforced
``check_system_core_buy_allowed`` for BUY but had NO cap guard for SELL, so a margin SELL that
opens a new short could exceed SYSTEM_CORE_MAX_OPEN_TRADES / one-active-per-coin on the live path.
A closing SELL (reduces exposure) must NEVER be blocked by this guard.

Patterns mirror ``test_short_protection.py`` (short entry = margin + no existing position +
shorting enabled).
"""
import asyncio
import unittest
from unittest.mock import MagicMock, Mock, patch


def _watchlist_item(symbol="DOT_USD"):
    w = Mock()
    w.symbol = symbol
    w.trade_enabled = True
    w.trade_amount_usd = 100.0
    w.trade_on_margin = True
    return w


class TestOrchestratorShortEntryCap(unittest.TestCase):
    def setUp(self):
        from app.services.signal_monitor import SignalMonitorService

        self.service = SignalMonitorService()
        self.db = MagicMock()

    def _place_sell(self):
        return asyncio.run(
            self.service._place_order_from_signal(
                db=self.db,
                symbol="DOT_USD",
                side="SELL",
                watchlist_item=_watchlist_item(),
                current_price=6.0,
                source="orchestrator",
            )
        )

    @patch("app.services.signal_monitor.trade_client")
    @patch("app.services.risk_guard.shorting_enabled", return_value=True)
    @patch("app.services.order_position_service.count_open_positions_for_symbol", return_value=0)
    @patch("app.services.live_trading_gate.assert_exchange_mutation_allowed")
    @patch("app.utils.live_trading.get_live_trading_status", return_value=False)
    def test_short_entry_over_cap_is_blocked_before_placement(
        self, _live, _gate, _count_pos, _shorting, mock_tc
    ):
        # No existing position + margin + shorting enabled => short entry => cap guard applies.
        with patch(
            "app.services.system_core_trade_guards.check_system_core_short_entry_allowed",
            return_value=(False, "system_core_max_open_trades count=3 max=3"),
        ):
            result = self._place_sell()

        self.assertTrue(result.get("blocked"))
        self.assertEqual(result["error"], "system_core_max_open_trades count=3 max=3")
        mock_tc.place_market_order.assert_not_called()
        # A block is a non-placement outcome -> the dedup slot must be released, not retained.
        self.assertNotIn("DOT_USD:SELL", self.service.order_creation_locks)

    @patch("app.services.signal_monitor.trade_client")
    @patch("app.services.risk_guard.shorting_enabled", return_value=True)
    @patch("app.services.order_position_service.count_open_positions_for_symbol", return_value=0)
    @patch("app.services.live_trading_gate.assert_exchange_mutation_allowed")
    @patch("app.utils.live_trading.get_live_trading_status", return_value=False)
    def test_short_entry_under_cap_places_order(
        self, _live, _gate, _count_pos, _shorting, mock_tc
    ):
        mock_tc.place_market_order.return_value = {
            "order_id": "short-1",
            "status": "FILLED",
            "cumulative_quantity": "16.6",
            "avg_price": "6.0",
        }
        with patch(
            "app.services.system_core_trade_guards.check_system_core_short_entry_allowed",
            return_value=(True, ""),
        ), patch.object(
            self.service, "_create_protection_after_entry_fill", return_value={"status": "ok"}
        ):
            result = self._place_sell()

        self.assertNotIn("error", result)
        mock_tc.place_market_order.assert_called_once()

    @patch("app.services.signal_monitor.trade_client")
    @patch("app.services.risk_guard.shorting_enabled", return_value=True)
    @patch("app.services.order_position_service.count_open_positions_for_symbol", return_value=1)
    @patch("app.services.live_trading_gate.assert_exchange_mutation_allowed")
    @patch("app.utils.live_trading.get_live_trading_status", return_value=False)
    def test_closing_sell_is_not_routed_through_short_cap(
        self, _live, _gate, _count_pos, _shorting, mock_tc
    ):
        # An existing position => this SELL CLOSES a long, not a short entry => the short cap guard
        # must NOT be consulted and must NOT block (reducing exposure is always allowed).
        mock_tc.place_market_order.return_value = {
            "order_id": "close-1",
            "status": "FILLED",
            "cumulative_quantity": "16.6",
            "avg_price": "6.0",
        }
        with patch(
            "app.services.system_core_trade_guards.check_system_core_short_entry_allowed",
            return_value=(False, "system_core_max_open_trades count=3 max=3"),
        ) as guard:
            result = self._place_sell()

        guard.assert_not_called()
        self.assertNotIn("error", result)
        mock_tc.place_market_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
