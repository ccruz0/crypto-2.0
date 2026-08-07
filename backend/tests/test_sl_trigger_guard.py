"""Tests for SL/TP trigger validation against live market."""

import unittest
from unittest.mock import MagicMock, patch

from app.utils.sl_trigger_guard import (
    compute_market_relative_sl,
    compute_market_relative_tp,
    derive_sl_percentage,
    ensure_tp_clear_of_market_after_tick,
    ensure_valid_sl_trigger,
    ensure_valid_tp_trigger,
    error_is_invalid_trigger_price,
    is_sl_trigger_valid,
    reference_price_for_trigger,
    summarize_format_variation_failure,
    tp_round_up_for_closing_side,
)


class TestTpTriggerValidity(unittest.TestCase):
    def test_short_tp_must_be_below_last(self):
        from app.utils.sl_trigger_guard import is_tp_trigger_valid

        self.assertTrue(is_tp_trigger_valid("SELL", 0.076, 0.07725))
        self.assertFalse(is_tp_trigger_valid("SELL", 0.0911, 0.07725))

    def test_long_tp_must_be_above_last(self):
        from app.utils.sl_trigger_guard import is_tp_trigger_valid

        self.assertTrue(is_tp_trigger_valid("BUY", 100.0, 95.0))
        self.assertFalse(is_tp_trigger_valid("BUY", 90.0, 95.0))

    def test_algo_style_stale_short_tp_repaired(self):
        from app.utils.sl_trigger_guard import (
            ensure_valid_tp_trigger,
            is_abs_level_valid_vs_entry,
        )

        self.assertFalse(
            is_abs_level_valid_vs_entry("SELL", 0.0911, 0.08386, is_tp=True)
        )
        repaired, reason = ensure_valid_tp_trigger(
            entry_side="SELL",
            tp_price=0.08302,  # entry-based 1% — still above last
            last_price=0.07725,
            tp_percentage=1.0,
            entry_price=0.08386,
        )
        self.assertIsNotNone(reason)
        self.assertLess(repaired, 0.07725)
        self.assertAlmostEqual(repaired, 0.07725 * 0.99, places=6)

    def test_algo_screenshot_short_tp_vs_last(self):
        """Aug 5 ALGO short: entry 0.0914 / last 0.0901 / 1% TP above last."""
        repaired, reason = ensure_valid_tp_trigger(
            entry_side="SELL",
            tp_price=0.0914 * 0.99,
            last_price=0.0901,
            tp_percentage=1.0,
            entry_price=0.0914,
        )
        self.assertIsNotNone(reason)
        self.assertLess(repaired, 0.0901)
        self.assertAlmostEqual(repaired, 0.0901 * 0.99, places=6)

    def test_short_tp_uses_conservative_bid_ref(self):
        """When bid < last, short TP must clear the lower (bid) ref."""
        ticker = {"last": 0.0901, "bid": 0.0895, "ask": 0.0903}
        # Entry-TP below last but above bid → still invalid vs bid
        repaired, reason = ensure_valid_tp_trigger(
            entry_side="SELL",
            tp_price=0.0898,
            last_price=0.0901,
            tp_percentage=1.0,
            entry_price=0.0914,
            ticker=ticker,
        )
        self.assertIsNotNone(reason)
        self.assertLess(repaired, 0.0895)
        self.assertAlmostEqual(repaired, 0.0895 * 0.99, places=6)

    def test_short_tp_valid_unchanged_when_below_market(self):
        price, reason = ensure_valid_tp_trigger(
            entry_side="SELL",
            tp_price=0.0880,
            last_price=0.0901,
            tp_percentage=3.0,
            entry_price=0.0914,
        )
        self.assertEqual(price, 0.0880)
        self.assertIsNone(reason)

    def test_long_tp_repaired_when_price_ran_through(self):
        repaired, reason = ensure_valid_tp_trigger(
            entry_side="BUY",
            tp_price=101.0,
            last_price=105.0,
            tp_percentage=1.0,
            entry_price=100.0,
        )
        self.assertIsNotNone(reason)
        self.assertGreater(repaired, 105.0)
        self.assertAlmostEqual(repaired, 105.0 * 1.01, places=6)


class TestReferenceAndRounding(unittest.TestCase):
    def test_reference_price_short_tp_uses_min_last_bid(self):
        ref = reference_price_for_trigger(
            "SELL",
            is_tp=True,
            ticker={"last": 0.0901, "bid": 0.0897, "ask": 0.0904},
        )
        self.assertAlmostEqual(ref, 0.0897)

    def test_reference_price_long_tp_uses_max_last_ask(self):
        ref = reference_price_for_trigger(
            "BUY",
            is_tp=True,
            ticker={"last": 100.0, "bid": 99.5, "ask": 100.4},
        )
        self.assertAlmostEqual(ref, 100.4)

    def test_tp_round_up_closing_side(self):
        self.assertTrue(tp_round_up_for_closing_side("SELL"))
        self.assertFalse(tp_round_up_for_closing_side("BUY"))

    def test_post_tick_clear_short_tp(self):
        # After coarse ROUND_UP, short TP landed on/above market → step down
        cleared = ensure_tp_clear_of_market_after_tick(
            entry_side="SELL",
            tp_price=0.0901,
            market_price=0.0901,
            tick_size=0.0001,
        )
        self.assertLess(cleared, 0.0901 * 0.999)


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
        self.assertAlmostEqual(compute_market_relative_tp("SELL", 0.0901, 1.0), 0.0901 * 0.99)

    def test_invalid_trigger_error_detect(self):
        self.assertTrue(error_is_invalid_trigger_price("Error 50007: INVALID_TRIGGER_PRICE"))
        self.assertFalse(error_is_invalid_trigger_price("INSUFFICIENT_BALANCE"))

    def test_summarize_surfaces_50007(self):
        msg = summarize_format_variation_failure(
            order_kind="TAKE_PROFIT_LIMIT",
            last_error="Error 50007: INVALID_TRIGGER_PRICE",
            attempts=9,
            trigger_price="0.0905",
            market_ref=0.0901,
        )
        self.assertIn("50007", msg)
        self.assertIn("short BUY-TP", msg)
        self.assertIn("0.0905", msg)


class TestCreateStopLossUsesGuard(unittest.TestCase):
    @patch("app.services.tp_sl_order_creator.trade_client")
    @patch("app.utils.sl_trigger_guard.fetch_ticker_prices", return_value={"last": 0.003483})
    def test_adjusts_before_place(self, _mock_ticker, mock_trade):
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


class TestCreateTakeProfitUsesGuard(unittest.TestCase):
    @patch("app.services.tp_sl_order_creator.trade_client")
    @patch(
        "app.utils.sl_trigger_guard.fetch_ticker_prices",
        return_value={"last": 0.0901, "bid": 0.0900, "ask": 0.0902},
    )
    def test_short_stale_tp_clamped_before_place(self, _mock_ticker, mock_trade):
        from app.services.tp_sl_order_creator import create_take_profit_order

        mock_trade.place_take_profit_order.return_value = {"order_id": "tp-1"}
        mock_trade._get_instrument_metadata.return_value = {
            "min_quantity": "1",
            "qty_tick_size": "1",
            "min_notional": "0",
            "quantity_decimals": 0,
            "price_tick_size": "0.0001",
        }
        mock_trade.normalize_quantity.return_value = "1311"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(
            tp_percentage=1.0,
            trade_on_margin=True,
            leverage=5.0,
        )

        with patch(
            "app.services.tp_sl_order_creator.can_place_real_order",
            return_value=(True, None),
        ), patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=None,
        ):
            result = create_take_profit_order(
                db=db,
                symbol="ALGO_USD",
                side="SELL",
                tp_price=0.0914 * 0.99,  # above last → invalid for short TP
                quantity=1311,
                entry_price=0.0914,
                parent_order_id="algo-parent",
                dry_run=False,
                source="manual",
            )

        self.assertEqual(result["order_id"], "tp-1")
        kwargs = mock_trade.place_take_profit_order.call_args.kwargs
        self.assertEqual(kwargs["side"], "BUY")
        self.assertLess(kwargs["price"], 0.0900)
        self.assertEqual(kwargs["trigger_price"], kwargs["price"])


if __name__ == "__main__":
    unittest.main()
