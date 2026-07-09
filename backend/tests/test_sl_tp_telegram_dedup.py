"""Tests for SL/TP Telegram deduplication and idempotent notification guards."""
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.exchange_sync import ExchangeSyncService, _protection_order_price


class TestProtectionOrderPrice(unittest.TestCase):
    def test_uses_price_field(self):
        order = ExchangeOrder(price=Decimal("1969.73"))
        self.assertAlmostEqual(_protection_order_price(order), 1969.73)

    def test_falls_back_to_trigger_condition(self):
        order = ExchangeOrder(price=None, trigger_condition=Decimal("1772.75"))
        self.assertAlmostEqual(_protection_order_price(order), 1772.75)

    def test_returns_none_when_missing(self):
        order = ExchangeOrder(price=None, trigger_condition=None)
        self.assertIsNone(_protection_order_price(order))


class TestSlTpImplIdempotency(unittest.TestCase):
    def test_already_protected_includes_db_prices(self):
        existing_sl = ExchangeOrder(
            exchange_order_id="sl-1",
            price=Decimal("1969.73"),
            order_role="STOP_LOSS",
            status=OrderStatusEnum.NEW,
        )
        existing_tp = ExchangeOrder(
            exchange_order_id="tp-1",
            price=Decimal("1772.75"),
            order_role="TAKE_PROFIT",
            status=OrderStatusEnum.NEW,
        )

        db = MagicMock()
        sl_query = MagicMock()
        sl_query.filter.return_value.order_by.return_value.first.return_value = existing_sl
        tp_query = MagicMock()
        tp_query.filter.return_value.order_by.return_value.first.return_value = existing_tp
        db.query.side_effect = [sl_query, tp_query]

        svc = ExchangeSyncService()
        result = svc._create_sl_tp_impl(
            db=db,
            symbol="ETH_USD",
            side_upper="SELL",
            filled_price_f=1790.66,
            filled_qty=0.0558,
            order_id="parent-1",
            source="test",
            strict_percentages=False,
            sl_price_override_f=None,
            tp_price_override_f=None,
        )

        self.assertEqual(result["status"], "already_protected")
        self.assertEqual(result["sl_result"]["order_id"], "sl-1")
        self.assertEqual(result["tp_result"]["order_id"], "tp-1")
        self.assertAlmostEqual(result["sl_price"], 1969.73)
        self.assertAlmostEqual(result["tp_price"], 1772.75)


class TestSlTpTelegramSkip(unittest.TestCase):
    @patch("app.services.telegram_notifier.telegram_notifier")
    @patch.object(ExchangeSyncService, "_create_sl_tp_impl")
    @patch("app.services.live_trading_gate.get_live_trading", return_value=True)
    def test_skips_telegram_when_already_protected(
        self, _live_trading, mock_impl, mock_notifier
    ):
        mock_impl.return_value = {
            "status": "already_protected",
            "sl_result": {"order_id": "sl-1", "error": None},
            "tp_result": {"order_id": "tp-1", "error": None},
            "sl_price": 1969.73,
            "tp_price": 1772.75,
            "oco_group_id": None,
            "skip_tp_creation": False,
            "skip_tp_reason": None,
        }

        db = MagicMock()
        filled_count_query = MagicMock()
        filled_count_query.filter.return_value.count.return_value = 0
        db.query.return_value = filled_count_query

        svc = ExchangeSyncService()
        svc.sync_open_orders = MagicMock()
        svc._sl_tp_creation_locks = {}

        result = svc._create_sl_tp_for_filled_order(
            db=db,
            symbol="ETH_USD",
            side="SELL",
            filled_price=1790.66,
            filled_qty=0.0558,
            order_id="parent-1",
            source="test",
        )

        self.assertEqual(result["status"], "already_protected")
        mock_notifier.send_sl_tp_orders.assert_not_called()
        mock_notifier.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
