"""Tests for SL trigger validation against live market."""

import unittest
from unittest.mock import MagicMock, patch

from app.utils.sl_trigger_guard import (
    compute_market_relative_sl,
    derive_sl_percentage,
    ensure_valid_sl_trigger,
    error_is_invalid_trigger_price,
    is_sl_trigger_valid,
)


class TestSlTriggerValidity(unittest.TestCase):
    def test_long_sl_must_be_below_last(self):
        self.assertTrue(is_sl_trigger_valid("BUY", 0.003, 0.0035))
        self.assertFalse(is_sl_trigger_valid("BUY", 0.004, 0.0035))

    def test_short_sl_must_be_above_last(self):
        self.assertTrue(is_sl_trigger_valid("SELL", 0.004, 0.0035))
        self.assertFalse(is_sl_trigger_valid("SELL", 0.003, 0.0035))


class TestEnsureValidSlTrigger(unittest.TestCase):
    def test_dgb_style_stale_absolute_repaired(self):
        repaired, reason = ensure_valid_sl_trigger(
            entry_side="BUY",
            sl_price=0.004,
            last_price=0.003483,
            sl_percentage=10.0,
            entry_price=0.004939,
        )
        self.assertIsNotNone(reason)
        self.assertLess(repaired, 0.003483)
        self.assertAlmostEqual(repaired, 0.003483 * 0.9, places=6)

    def test_valid_price_unchanged(self):
        price, reason = ensure_valid_sl_trigger(
            entry_side="BUY",
            sl_price=0.003,
            last_price=0.0035,
            sl_percentage=10.0,
        )
        self.assertEqual(price, 0.003)
        self.assertIsNone(reason)

    def test_no_last_leaves_price(self):
        price, reason = ensure_valid_sl_trigger(
            entry_side="BUY",
            sl_price=0.004,
            last_price=None,
        )
        self.assertEqual(price, 0.004)
        self.assertIsNone(reason)


class TestHelpers(unittest.TestCase):
    def test_derive_and_compute(self):
        pct = derive_sl_percentage("BUY", 100.0, 90.0, None)
        self.assertAlmostEqual(pct, 10.0)
        self.assertAlmostEqual(compute_market_relative_sl("BUY", 50.0, 10.0), 45.0)
        self.assertAlmostEqual(compute_market_relative_sl("SELL", 50.0, 10.0), 55.0)

    def test_invalid_trigger_error_detect(self):
        self.assertTrue(error_is_invalid_trigger_price("Error 50007: INVALID_TRIGGER_PRICE"))
        self.assertFalse(error_is_invalid_trigger_price("INSUFFICIENT_BALANCE"))


class TestCreateStopLossUsesGuard(unittest.TestCase):
    @patch("app.services.tp_sl_order_creator.trade_client")
    @patch("app.utils.sl_trigger_guard.fetch_last_price", return_value=0.003483)
    def test_adjusts_before_place(self, _mock_last, mock_trade):
        from app.services.tp_sl_order_creator import create_stop_loss_order

        mock_trade.place_stop_loss_order.return_value = {"order_id": "sl-1"}
        mock_trade._get_instrument_metadata.return_value = {
            "min_quantity": "10",
            "qty_tick_size": "10",
            "min_notional": "0",
            "quantity_decimals": 0,
        }
        mock_trade.normalize_quantity.return_value = "4020"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(
            sl_percentage=10.0,
            trade_on_margin=False,
            leverage=None,
        )

        with patch(
            "app.services.tp_sl_order_creator.can_place_real_order",
            return_value=(True, None),
        ), patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=None,
        ):
            result = create_stop_loss_order(
                db=db,
                symbol="DGB_USD",
                side="BUY",
                sl_price=0.004,  # stale / above market
                quantity=4020,
                entry_price=0.004939,
                parent_order_id="parent-1",
                dry_run=False,
                source="test",
                sl_percentage=10.0,
            )

        self.assertEqual(result["order_id"], "sl-1")
        kwargs = mock_trade.place_stop_loss_order.call_args.kwargs
        self.assertLess(kwargs["price"], 0.003483)
        self.assertAlmostEqual(kwargs["price"], 0.003483 * 0.9, places=6)
        self.assertEqual(kwargs["trigger_price"], kwargs["price"])


if __name__ == "__main__":
    unittest.main()
