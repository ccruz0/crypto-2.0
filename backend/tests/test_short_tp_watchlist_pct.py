"""Tests: short TP must use agreed watchlist price (no market-based adjust)."""
import unittest
from unittest.mock import MagicMock, Mock, patch

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.watchlist import WatchlistItem
from app.services.sl_tp_checker import SLTPCheckerService
from app.services.tp_sl_order_creator import create_take_profit_order


class TestShortTpUsesAgreedWatchlistPrice(unittest.TestCase):
    @patch("app.services.tp_sl_order_creator.can_place_real_order")
    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_short_tp_places_agreed_price_when_market_past_target(
        self, mock_trade_client, mock_can_place
    ):
        """Entry 0.8984, 1% TP ~0.8894, market past target — still place agreed TP."""
        mock_can_place.return_value = (True, None)
        mock_trade_client.place_take_profit_order.return_value = {"order_id": "tp-agreed"}
        mock_trade_client._get_instrument_metadata.return_value = {
            "min_quantity": "0.001",
            "qty_tick_size": "0.001",
            "min_notional": "0",
            "quantity_decimals": 8,
        }
        mock_trade_client.normalize_quantity.return_value = "0.01"

        entry = 0.8984
        tp_price = entry * (1 - 1.0 / 100)  # 0.889416

        result = create_take_profit_order(
            db=MagicMock(),
            symbol="BTC_USD",
            side="SELL",
            tp_price=tp_price,
            quantity=0.01,
            entry_price=entry,
            dry_run=False,
            source="auto",
        )

        self.assertEqual(result["order_id"], "tp-agreed")
        placed_price = mock_trade_client.place_take_profit_order.call_args.kwargs["price"]
        self.assertAlmostEqual(placed_price, tp_price, places=4)

    @patch("app.services.tp_sl_order_creator.can_place_real_order")
    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_short_tp_keeps_watchlist_price_when_valid(
        self, mock_trade_client, mock_can_place
    ):
        """Auto path keeps calculated watchlist TP (no market adjust)."""
        mock_can_place.return_value = (True, None)
        mock_trade_client.place_take_profit_order.return_value = {"order_id": "tp-ok"}
        mock_trade_client._get_instrument_metadata.return_value = {
            "min_quantity": "0.001",
            "qty_tick_size": "0.001",
            "min_notional": "0",
            "quantity_decimals": 8,
        }
        mock_trade_client.normalize_quantity.return_value = "0.01"

        entry = 0.8984
        tp_price = round(entry * (1 - 1.0 / 100), 4)

        result = create_take_profit_order(
            db=MagicMock(),
            symbol="BTC_USD",
            side="SELL",
            tp_price=tp_price,
            quantity=0.01,
            entry_price=entry,
            dry_run=False,
            source="auto",
        )

        self.assertEqual(result["order_id"], "tp-ok")
        placed_price = mock_trade_client.place_take_profit_order.call_args.kwargs["price"]
        self.assertAlmostEqual(placed_price, tp_price, places=4)


class TestSlTpCheckerPrefersTpPercentage(unittest.TestCase):
    @patch("app.services.sl_tp_checker.trade_client")
    def test_stale_tp_price_overridden_by_tp_percentage(self, mock_trade_client):
        mock_trade_client.get_account_summary.return_value = {
            "accounts": [{"currency": "BTC", "balance": "1.0"}]
        }

        db = MagicMock()
        watchlist_item = Mock()
        watchlist_item.sl_price = None
        watchlist_item.tp_price = 0.840  # stale widened TP from old auto-adjust
        watchlist_item.sl_tp_mode = "conservative"
        watchlist_item.sl_percentage = 3.0
        watchlist_item.tp_percentage = 1.0
        watchlist_item.skip_sl_tp_reminder = False
        watchlist_item.purchase_price = None
        watchlist_item.price = None

        sell_entry = Mock(spec=ExchangeOrder)
        sell_entry.symbol = "BTC_USD"
        sell_entry.side = OrderSideEnum.SELL
        sell_entry.status = OrderStatusEnum.FILLED
        sell_entry.order_role = None
        sell_entry.avg_price = 0.8984
        sell_entry.price = 0.8984
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

        def capture_tp(**kwargs):
            captured["tp_price"] = kwargs.get("tp_price")
            return {"order_id": "tp-1"}

        checker = SLTPCheckerService()
        with patch("app.services.sl_tp_protection.get_active_protection_order", return_value=None), patch(
            "app.services.sl_tp_checker.telegram_notifier"
        ), patch("app.services.sl_tp_checker.create_stop_loss_order", return_value={"order_id": "sl-1"}), patch(
            "app.services.sl_tp_checker.create_take_profit_order", side_effect=capture_tp
        ):
            result = checker._create_protection_order(db, "BTC_USD", create_sl=False, create_tp=True)

        self.assertTrue(result.get("success"))
        expected_tp = round(0.8984 * (1 - 1.0 / 100), 4)
        self.assertAlmostEqual(captured["tp_price"], expected_tp, places=4)
        self.assertNotAlmostEqual(captured["tp_price"], 0.840, places=3)


class TestDashboardClearsTpPriceOnPctUpdate(unittest.TestCase):
    def test_apply_watchlist_updates_clears_tp_price(self):
        from app.api.routes_dashboard import _apply_watchlist_updates

        item = Mock()
        item.symbol = "BTC_USD"
        item.tp_percentage = 3.0
        item.tp_price = 0.840
        item.set_field_updated_at = Mock()

        _apply_watchlist_updates(item, {"tp_percentage": 1.0})

        self.assertEqual(item.tp_percentage, 1.0)
        self.assertIsNone(item.tp_price)
        item.set_field_updated_at.assert_called_with("tp_price")


if __name__ == "__main__":
    unittest.main()
