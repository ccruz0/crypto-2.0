"""Tests for SL/TP protection idempotency helpers and duplicate prevention."""
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.sl_tp_protection import (
    get_active_protection_order,
    has_complete_sl_tp_protection,
    is_flatten_close_order,
    is_flatten_close_role,
    mark_flatten_close_order,
    should_skip_rejected_tp_backfill,
    wallet_balance_matches_entry_side,
)
from app.services.tp_sl_order_creator import create_stop_loss_order, create_take_profit_order


class TestSlTpProtectionHelpers(unittest.TestCase):
    def test_has_complete_protection_when_both_legs_active(self):
        db = MagicMock()
        sl = ExchangeOrder(exchange_order_id="sl-1", order_role="STOP_LOSS", status=OrderStatusEnum.ACTIVE)
        tp = ExchangeOrder(exchange_order_id="tp-1", order_role="TAKE_PROFIT", status=OrderStatusEnum.ACTIVE)

        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            side_effect=[sl, tp],
        ):
            self.assertTrue(has_complete_sl_tp_protection(db, "parent-1"))

    def test_missing_tp_is_not_complete(self):
        db = MagicMock()
        sl = ExchangeOrder(exchange_order_id="sl-1", order_role="STOP_LOSS", status=OrderStatusEnum.ACTIVE)

        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            side_effect=[sl, None],
        ), patch(
            "app.services.sl_tp_protection.has_filled_sl_tp_protection",
            return_value=False,
        ):
            self.assertFalse(has_complete_sl_tp_protection(db, "parent-1"))

    def test_filled_stubs_count_as_complete(self):
        db = MagicMock()
        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=None,
        ), patch(
            "app.services.sl_tp_protection.has_filled_sl_tp_protection",
            return_value=True,
        ):
            self.assertTrue(has_complete_sl_tp_protection(db, "parent-1"))

    def test_wallet_balance_matches_entry_side(self):
        self.assertTrue(wallet_balance_matches_entry_side("BUY", 1.5))
        self.assertFalse(wallet_balance_matches_entry_side("BUY", -1.5))
        self.assertTrue(wallet_balance_matches_entry_side("SELL", -0.2))
        self.assertFalse(wallet_balance_matches_entry_side("SELL", 1.89))
        self.assertFalse(wallet_balance_matches_entry_side("SELL", 0.0))

    def test_flatten_close_role_helpers(self):
        self.assertTrue(is_flatten_close_role("FLATTEN"))
        self.assertTrue(is_flatten_close_role("flatten"))
        self.assertFalse(is_flatten_close_role("STOP_LOSS"))
        self.assertFalse(is_flatten_close_role(None))
        tagged = ExchangeOrder(
            exchange_order_id="close-1",
            order_role="FLATTEN",
            status=OrderStatusEnum.FILLED,
        )
        self.assertTrue(is_flatten_close_order(tagged))
        self.assertFalse(is_flatten_close_order(None))
        self.assertFalse(
            is_flatten_close_order(
                ExchangeOrder(exchange_order_id="e1", order_role=None, status=OrderStatusEnum.FILLED)
            )
        )

    def test_mark_flatten_close_order_updates_existing(self):
        db = MagicMock()
        existing = MagicMock()
        existing.parent_order_id = None
        db.query.return_value.filter.return_value.first.return_value = existing

        mark_flatten_close_order(
            db,
            close_order_id="5755600492527623825",
            entry_order_id="5755600492527622305",
            symbol="SUI_USD",
            close_side="BUY",
            quantity=72.3,
        )

        self.assertEqual(existing.order_role, "FLATTEN")
        self.assertEqual(existing.parent_order_id, "5755600492527622305")
        db.commit.assert_called_once()

    def test_protection_closing_side_matches_wallet(self):
        from app.services.sl_tp_protection import protection_closing_side_matches_wallet

        self.assertTrue(protection_closing_side_matches_wallet("SELL", 10.0))
        self.assertFalse(protection_closing_side_matches_wallet("SELL", -10.0))
        self.assertTrue(protection_closing_side_matches_wallet("BUY", -5.0))
        self.assertFalse(protection_closing_side_matches_wallet("BUY", 5.0))

    def test_should_send_protection_rejected_alert_gates(self):
        from app.services.sl_tp_protection import should_send_protection_rejected_alert

        self.assertFalse(
            should_send_protection_rejected_alert(
                None,
                old_status=OrderStatusEnum.REJECTED,
                order_id="oid-1",
                symbol="ALGO_USD",
                order_role="TAKE_PROFIT",
                reject_reason="INSUFFICIENT_ACC_BALANCE",
            )
        )
        self.assertFalse(
            should_send_protection_rejected_alert(
                None,
                old_status=OrderStatusEnum.ACTIVE,
                order_id="oid-2",
                symbol="ALGO_USD",
                order_role="TAKE_PROFIT",
                reject_reason="INSUFFICIENT_ACC_BALANCE",
            )
        )
        self.assertTrue(
            should_send_protection_rejected_alert(
                None,
                old_status=OrderStatusEnum.ACTIVE,
                order_id="oid-3",
                symbol="ALGO_USD",
                order_role="STOP_LOSS",
                reject_reason="INVALID_TRIGGER_PRICE",
            )
        )
        # Dedup: second claim for same order_id suppressed
        self.assertFalse(
            should_send_protection_rejected_alert(
                None,
                old_status=OrderStatusEnum.NEW,
                order_id="oid-3",
                symbol="ALGO_USD",
                order_role="STOP_LOSS",
                reject_reason="INVALID_TRIGGER_PRICE",
            )
        )

    def test_skip_rejected_tp_backfill_when_sl_active(self):
        db = MagicMock()
        sl = ExchangeOrder(exchange_order_id="sl-1", order_role="STOP_LOSS", status=OrderStatusEnum.ACTIVE)
        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=sl,
        ), patch(
            "app.services.sl_tp_protection.has_rejected_protection_order",
            return_value=True,
        ), patch(
            "app.services.tp_sl_order_creator.is_native_oco_enabled",
            return_value=False,
        ):
            self.assertTrue(should_skip_rejected_tp_backfill(db, "parent-1"))

    def test_do_not_skip_rejected_tp_when_spot_oco_heal_enabled(self):
        db = MagicMock()
        parent = ExchangeOrder(exchange_order_id="parent-1", symbol="ALGO_USD")
        sl = ExchangeOrder(exchange_order_id="sl-1", order_role="STOP_LOSS", status=OrderStatusEnum.ACTIVE)
        db.query.return_value.filter.return_value.first.return_value = parent
        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=sl,
        ), patch(
            "app.services.sl_tp_protection.has_rejected_protection_order",
            return_value=True,
        ), patch(
            "app.services.tp_sl_order_creator.is_native_oco_enabled",
            return_value=True,
        ), patch(
            "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
            return_value=(False, None),
        ):
            self.assertFalse(should_skip_rejected_tp_backfill(db, "parent-1"))


class TestTpSlCreatorIdempotency(unittest.TestCase):
    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_create_stop_loss_reuses_active_order(self, mock_trade_client):
        db = MagicMock()
        existing = ExchangeOrder(
            exchange_order_id="sl-existing",
            order_role="STOP_LOSS",
            status=OrderStatusEnum.ACTIVE,
            quantity=0.0558,
        )
        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=existing,
        ):
            result = create_stop_loss_order(
                db=db,
                symbol="ETH_USD",
                side="SELL",
                sl_price=1969.73,
                quantity=0.0558,
                entry_price=1790.66,
                parent_order_id="parent-1",
                dry_run=False,
                source="auto",
            )
        self.assertEqual(result["order_id"], "sl-existing")
        self.assertIsNone(result["error"])
        mock_trade_client.place_stop_loss_order.assert_not_called()

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_create_stop_loss_places_when_existing_undercovers(self, mock_trade_client):
        """Gap fill must not reuse a smaller active SL (ops ALGO undercoverage)."""
        db = MagicMock()
        existing = ExchangeOrder(
            exchange_order_id="sl-small",
            order_role="STOP_LOSS",
            status=OrderStatusEnum.ACTIVE,
            quantity=124.0,
        )
        mock_trade_client.place_stop_loss_order.return_value = {"order_id": "sl-gap"}
        mock_trade_client._get_instrument_metadata.return_value = {
            "min_quantity": "1",
            "qty_tick_size": "1",
            "min_notional": "0",
            "quantity_decimals": 0,
        }
        mock_trade_client.normalize_quantity.return_value = "470"
        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=existing,
        ), patch(
            "app.services.tp_sl_order_creator.can_place_real_order",
            return_value=(True, None),
        ), patch(
            "app.utils.sl_trigger_guard.fetch_last_price",
            return_value=0.08,
        ):
            result = create_stop_loss_order(
                db=db,
                symbol="ALGO_USD",
                side="SELL",
                sl_price=0.0845,
                quantity=470.0,
                entry_price=0.0804,
                parent_order_id="parent-algo",
                dry_run=False,
                source="manual",
                sl_percentage=10.0,
            )
        self.assertEqual(result["order_id"], "sl-gap")
        self.assertIsNone(result["error"])
        mock_trade_client.place_stop_loss_order.assert_called_once()

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_create_take_profit_reuses_active_order(self, mock_trade_client):
        db = MagicMock()
        existing = ExchangeOrder(
            exchange_order_id="tp-existing",
            order_role="TAKE_PROFIT",
            status=OrderStatusEnum.ACTIVE,
        )
        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=existing,
        ):
            result = create_take_profit_order(
                db=db,
                symbol="ETH_USD",
                side="SELL",
                tp_price=1736.52,
                quantity=0.0558,
                entry_price=1790.66,
                parent_order_id="parent-1",
                dry_run=False,
                source="auto",
            )
        self.assertEqual(result["order_id"], "tp-existing")
        self.assertIsNone(result["error"])
        mock_trade_client.place_take_profit_order.assert_not_called()


class TestTelegramProtectionMessages(unittest.TestCase):
    def test_sl_tp_created_message_includes_position_context(self):
        from app.services.telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.send_sl_tp_orders(
                symbol="ETH_USD",
                sl_price=1969.73,
                tp_price=1736.52,
                quantity=0.0558,
                mode="conservative",
                sl_order_id="sl-1",
                tp_order_id="tp-1",
                original_order_id="parent-1",
                sl_side="BUY",
                tp_side="BUY",
                entry_price=1790.66,
                original_order_side="SELL",
            )
        message = mock_send.call_args[0][0]
        self.assertIn("SHORT (opened via SELL entry)", message)
        self.assertIn("exit orders (BUY)", message)
        self.assertIn("Entry Order:", message)

    def test_sync_cancelled_protection_message(self):
        from app.services.telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        message = notifier.format_sync_cancelled_order_message(
            symbol="ETH_USD",
            side="BUY",
            order_type="TAKE_PROFIT_LIMIT",
            order_id="tp-old",
            order_role="TAKE_PROFIT",
            parent_order_id="parent-1",
            parent_entry_side="SELL",
            price=1745.17,
            quantity=0.0558,
        )
        self.assertIn("PROTECTION ORDER CANCELLED", message)
        self.assertIn("SHORT (opened via SELL entry)", message)
        self.assertIn("exit order", message)
