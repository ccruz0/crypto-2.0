"""Tests for indicator formatting and always-on SL/TP ensure."""

import unittest
from unittest.mock import MagicMock, patch

from app.utils.indicator_format import format_indicator_value
from app.services.sl_tp_checker import (
    SLTPCheckerService,
    _classify_open_protection_leg,
)


class TestIndicatorFormat(unittest.TestCase):
    def test_sub_dollar_not_zero(self):
        self.assertEqual(format_indicator_value(0.00326), "0.00326")
        self.assertNotEqual(format_indicator_value(0.00326), "0.00")

    def test_large_price_two_decimals(self):
        self.assertEqual(format_indicator_value(65199.576), "65199.58")

    def test_none(self):
        self.assertEqual(format_indicator_value(None), "N/A")


class TestClassifyProtectionLeg(unittest.TestCase):
    def test_advanced_take_profit(self):
        self.assertEqual(
            _classify_open_protection_leg(
                {
                    "order_type": "TAKE_PROFIT_LIMIT",
                    "status": "ACTIVE",
                    "source_endpoint": "private/advanced/get-open-orders",
                }
            ),
            "TP",
        )

    def test_stop_limit_is_sl(self):
        self.assertEqual(
            _classify_open_protection_leg({"order_type": "STOP_LIMIT", "status": "ACTIVE"}),
            "SL",
        )

    def test_regular_limit_not_protection(self):
        self.assertIsNone(
            _classify_open_protection_leg(
                {"order_type": "LIMIT", "side": "BUY", "status": "ACTIVE"}
            )
        )


class TestEnsureMissingProtection(unittest.TestCase):
    @patch.object(SLTPCheckerService, "_create_protection_order")
    @patch.object(SLTPCheckerService, "check_positions_for_sl_tp")
    def test_auto_creates_only_missing_leg(self, mock_check, mock_create):
        svc = SLTPCheckerService()
        mock_check.return_value = {
            "positions_missing_sl_tp": [
                {
                    "symbol": "DGB_USD",
                    "currency": "DGB",
                    "balance": 4028.0,
                    "has_sl": False,
                    "has_tp": True,
                    "sl_price": None,
                    "tp_price": 0.005,
                    "skip_reminder": False,
                }
            ],
            "total_positions": 1,
            "oco_issues": {},
            "checked_at": None,
        }
        mock_create.return_value = {
            "success": True,
            "sl_order_id": "sl-1",
            "tp_order_id": None,
        }

        result = svc.ensure_missing_protection(MagicMock())

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        self.assertTrue(kwargs["create_sl"])
        self.assertFalse(kwargs["create_tp"])
        self.assertTrue(kwargs["force"])
        self.assertEqual(kwargs["source"], "auto_ensure")
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(result["still_missing"], [])


class TestCheckPositionsUsesUnifiedOrders(unittest.TestCase):
    @patch.object(SLTPCheckerService, "_check_oco_issues", return_value={})
    @patch("app.services.sl_tp_checker.fetch_unified_open_orders")
    @patch("app.services.sl_tp_checker.trade_client")
    def test_detects_advanced_tp_without_sl(self, mock_trade, mock_fetch, _mock_oco):
        mock_trade.get_account_summary.return_value = {
            "accounts": [{"currency": "DGB", "balance": "4028"}]
        }
        mock_fetch.return_value = {
            "data_verified": True,
            "trigger_orders_status": "ok",
            "advanced_orders_status": "ok",
            "all_raw_orders": [
                {
                    "instrument_name": "DGB_USD",
                    "order_type": "TAKE_PROFIT_LIMIT",
                    "order_status": "ACTIVE",
                    "quantity": "4020",
                    "order_id": "tp-adv-1",
                    "side": "SELL",
                }
            ],
        }
        db = MagicMock()
        # watchlist lookup returns None
        db.query.return_value.filter.return_value.first.return_value = None

        svc = SLTPCheckerService()
        result = svc.check_positions_for_sl_tp(db)

        missing = result["positions_missing_sl_tp"]
        self.assertEqual(len(missing), 1)
        self.assertFalse(missing[0]["has_sl"])
        self.assertTrue(missing[0]["has_tp"])


if __name__ == "__main__":
    unittest.main()
