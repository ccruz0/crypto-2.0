"""Tests for short-position SL/TP protection (entry SELL, closing BUY orders)."""
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.watchlist import WatchlistItem
from app.services.exchange_sync import ExchangeSyncService
from app.services.sl_tp_checker import (
    SLTPCheckerService,
    _compute_sl_tp_from_entry,
    _entry_side_from_order,
)
from app.services.tp_sl_order_creator import get_closing_side_from_entry


class TestShortProtectionFormulas(unittest.TestCase):
    def test_sell_entry_sl_above_tp_below(self):
        entry = 100.0
        sl_pct = 3.0
        tp_pct = 3.0
        sl_price, tp_price = _compute_sl_tp_from_entry(entry, "SELL", sl_pct, tp_pct)
        self.assertAlmostEqual(sl_price, entry * (1 + sl_pct / 100))
        self.assertAlmostEqual(tp_price, entry * (1 - tp_pct / 100))
        self.assertGreater(sl_price, entry)
        self.assertLess(tp_price, entry)

    def test_buy_entry_sl_below_tp_above(self):
        entry = 100.0
        sl_pct = 3.0
        tp_pct = 3.0
        sl_price, tp_price = _compute_sl_tp_from_entry(entry, "BUY", sl_pct, tp_pct)
        self.assertAlmostEqual(sl_price, entry * (1 - sl_pct / 100))
        self.assertAlmostEqual(tp_price, entry * (1 + tp_pct / 100))
        self.assertLess(sl_price, entry)
        self.assertGreater(tp_price, entry)

    def test_closing_side_for_short_entry(self):
        self.assertEqual(get_closing_side_from_entry("SELL"), "BUY")
        self.assertEqual(get_closing_side_from_entry("BUY"), "SELL")


class TestExchangeSyncShortImpl(unittest.TestCase):
    @patch("app.services.exchange_sync.get_active_protection_order", return_value=None)
    @patch("app.services.tp_sl_order_creator.is_native_oco_enabled", return_value=False)
    @patch("app.services.tp_sl_order_creator.create_take_profit_order")
    @patch("app.services.tp_sl_order_creator.create_stop_loss_order")
    def test_create_sl_tp_impl_sell_uses_inverted_prices(
        self, mock_sl_create, mock_tp_create, _native_oco_off, _no_existing
    ):
        mock_sl_create.return_value = {"order_id": "sl-short"}
        mock_tp_create.return_value = {"order_id": "tp-short"}

        db = MagicMock()
        watchlist_item = Mock()
        watchlist_item.sl_tp_mode = "conservative"
        watchlist_item.sl_percentage = 3.0
        watchlist_item.tp_percentage = 3.0
        watchlist_item.trade_on_margin = False
        watchlist_item.leverage = None
        db.query.return_value.filter.return_value.first.return_value = watchlist_item

        svc = ExchangeSyncService()
        result = svc._create_sl_tp_impl(
            db=db,
            symbol="ETH_USDT",
            side_upper="SELL",
            filled_price_f=2000.0,
            filled_qty=0.5,
            order_id="sell-entry-1",
            source="test",
            strict_percentages=False,
            sl_price_override_f=None,
            tp_price_override_f=None,
        )

        self.assertAlmostEqual(result["sl_price"], 2000.0 * 1.03)
        self.assertAlmostEqual(result["tp_price"], 2000.0 * 0.97)
        sl_kwargs = mock_sl_create.call_args.kwargs
        tp_kwargs = mock_tp_create.call_args.kwargs
        self.assertEqual(sl_kwargs["side"], "SELL")
        self.assertEqual(tp_kwargs["side"], "SELL")


class TestPlaceOrderFromSignalShortProtection(unittest.TestCase):
    def setUp(self):
        from app.services.signal_monitor import SignalMonitorService

        self.service = SignalMonitorService()
        self.db = MagicMock()
        self.watchlist_item = Mock()
        self.watchlist_item.trade_amount_usd = 100.0
        self.watchlist_item.trade_on_margin = True

    @patch("app.services.signal_monitor.trade_client")
    @patch("app.services.risk_guard.shorting_enabled", return_value=True)
    @patch("app.services.order_position_service.count_open_positions_for_symbol", return_value=0)
    @patch("app.services.live_trading_gate.assert_exchange_mutation_allowed")
    @patch("app.utils.live_trading.get_live_trading_status", return_value=False)
    def test_sell_short_entry_triggers_protection(
        self,
        _live,
        _gate,
        _count_pos,
        _shorting,
        mock_trade_client,
    ):
        import asyncio

        mock_trade_client.place_market_order.return_value = {
            "order_id": "short-entry-99",
            "status": "FILLED",
            "cumulative_quantity": "0.05",
            "avg_price": "2000.0",
        }
        mock_trade_client.normalize_quantity_safe_with_fallback.return_value = ("0.05", {})

        with patch.object(
            self.service,
            "_create_protection_after_entry_fill",
            return_value={"sl_result": {"order_id": "sl"}, "tp_result": {"order_id": "tp"}},
        ) as mock_protect:
            result = asyncio.run(
                self.service._place_order_from_signal(
                    db=self.db,
                    symbol="ETH_USDT",
                    side="SELL",
                    watchlist_item=self.watchlist_item,
                    current_price=2000.0,
                    source="test",
                )
            )

        self.assertNotIn("error", result)
        mock_protect.assert_called_once()
        call_kwargs = mock_protect.call_args.kwargs
        self.assertEqual(call_kwargs["entry_side"], "SELL")
        self.assertEqual(call_kwargs["order_id"], "short-entry-99")

    @patch("app.services.signal_monitor.trade_client")
    @patch("app.services.live_trading_gate.assert_exchange_mutation_allowed")
    @patch("app.utils.live_trading.get_live_trading_status", return_value=False)
    def test_buy_entry_triggers_protection(self, _live, _gate, mock_trade_client):
        import asyncio

        mock_trade_client.place_market_order.return_value = {
            "order_id": "buy-entry-1",
            "status": "FILLED",
            "cumulative_quantity": "0.05",
            "avg_price": "2000.0",
        }

        with patch.object(
            self.service,
            "_create_protection_after_entry_fill",
            return_value={"sl_result": {"order_id": "sl"}, "tp_result": {"order_id": "tp"}},
        ) as mock_protect:
            result = asyncio.run(
                self.service._place_order_from_signal(
                    db=self.db,
                    symbol="ETH_USDT",
                    side="BUY",
                    watchlist_item=self.watchlist_item,
                    current_price=2000.0,
                    source="test",
                )
            )

        self.assertNotIn("error", result)
        mock_protect.assert_called_once()
        self.assertEqual(mock_protect.call_args.kwargs["entry_side"], "BUY")


class TestSlTpCheckerEntrySide(unittest.TestCase):
    def test_entry_side_from_sell_order(self):
        order = Mock()
        order.side = OrderSideEnum.SELL
        self.assertEqual(_entry_side_from_order(order), "SELL")

    @patch("app.services.sl_tp_checker.trade_client")
    def test_create_protection_order_uses_sell_entry_side(self, mock_trade_client):
        mock_trade_client.get_account_summary.return_value = {
            "accounts": [{"currency": "ETH", "balance": "1.0"}]
        }
        mock_trade_client.place_stop_loss_order = MagicMock(return_value={"order_id": "sl-1"})
        mock_trade_client.place_take_profit_order = MagicMock(return_value={"order_id": "tp-1"})

        db = MagicMock()
        watchlist_item = Mock()
        watchlist_item.sl_price = None
        watchlist_item.tp_price = None
        watchlist_item.sl_tp_mode = "conservative"
        watchlist_item.sl_percentage = 3.0
        watchlist_item.tp_percentage = 3.0
        watchlist_item.skip_sl_tp_reminder = False
        watchlist_item.purchase_price = None
        watchlist_item.price = None

        sell_entry = Mock(spec=ExchangeOrder)
        sell_entry.symbol = "ETH_USDT"
        sell_entry.side = OrderSideEnum.SELL
        sell_entry.status = OrderStatusEnum.FILLED
        sell_entry.order_role = None
        sell_entry.avg_price = 2000.0
        sell_entry.price = 2000.0
        sell_entry.exchange_order_id = "sell-entry-1"
        sell_entry.exchange_create_time = None

        query_mock = MagicMock()
        filter_mock = MagicMock()

        def query_side_effect(model):
            if model is WatchlistItem:
                q = MagicMock()
                q.filter.return_value.first.return_value = watchlist_item
                return q
            if model is ExchangeOrder:
                return filter_mock
            return query_mock

        filter_mock.filter.return_value = filter_mock
        filter_mock.order_by.return_value.first.return_value = sell_entry
        db.query.side_effect = query_side_effect

        captured = {}

        def capture_sl(**kwargs):
            captured["sl_side"] = kwargs.get("side")
            captured["sl_price"] = kwargs.get("sl_price")
            return {"order_id": "sl-1"}

        def capture_tp(**kwargs):
            captured["tp_side"] = kwargs.get("side")
            captured["tp_price"] = kwargs.get("tp_price")
            return {"order_id": "tp-1"}

        checker = SLTPCheckerService()
        with patch("app.services.sl_tp_checker.create_stop_loss_order", side_effect=capture_sl), patch(
            "app.services.sl_tp_checker.create_take_profit_order", side_effect=capture_tp
        ):
            result = checker._create_protection_order(db, "ETH_USDT", create_sl=True, create_tp=True)

        self.assertTrue(result.get("success"))
        self.assertEqual(captured["sl_side"], "SELL")
        self.assertEqual(captured["tp_side"], "SELL")
        self.assertGreater(captured["sl_price"], 2000.0)
        self.assertLess(captured["tp_price"], 2000.0)


if __name__ == "__main__":
    unittest.main()
