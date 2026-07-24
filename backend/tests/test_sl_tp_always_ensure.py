"""Tests for indicator formatting and always-on SL/TP ensure."""

import unittest
from unittest.mock import MagicMock, patch

from app.utils.indicator_format import format_indicator_value
from app.services.sl_tp_checker import (
    SLTPCheckerService,
    _classify_open_protection_leg,
    _derive_entry_from_abs_prices,
    _entry_symbol_variants,
    _order_entry_price,
    _protection_quantities_cover_position,
    _quantity_matches_position,
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


class TestEntrySymbolVariants(unittest.TestCase):
    def test_usdt_includes_usd(self):
        self.assertEqual(_entry_symbol_variants("AKT_USDT"), ["AKT_USDT", "AKT_USD"])

    def test_usd_includes_usdt(self):
        self.assertEqual(_entry_symbol_variants("AKT_USD"), ["AKT_USD", "AKT_USDT"])

    def test_bare_includes_both(self):
        self.assertEqual(
            _entry_symbol_variants("AKT"),
            ["AKT", "AKT_USDT", "AKT_USD"],
        )


class TestOrderEntryPrice(unittest.TestCase):
    def test_avg_price_preferred(self):
        order = MagicMock(avg_price=1.5, price=1.0, cumulative_value=None, cumulative_quantity=None)
        self.assertEqual(_order_entry_price(order), 1.5)

    def test_cumulative_fallback(self):
        order = MagicMock(
            avg_price=None,
            price=None,
            cumulative_value=10.0,
            cumulative_quantity=4.0,
        )
        self.assertEqual(_order_entry_price(order), 2.5)


class TestDeriveEntryFromAbs(unittest.TestCase):
    def test_long_from_tp_pct(self):
        # tp = entry * 1.01 => entry = tp / 1.01
        entry = _derive_entry_from_abs_prices(
            entry_side="BUY",
            sl_price=None,
            tp_price=1.01,
            sl_percentage=None,
            tp_percentage=1.0,
        )
        self.assertAlmostEqual(entry, 1.0, places=6)

    def test_long_from_sl_pct(self):
        # sl = entry * 0.9 => entry = sl / 0.9
        entry = _derive_entry_from_abs_prices(
            entry_side="BUY",
            sl_price=0.9,
            tp_price=None,
            sl_percentage=10.0,
            tp_percentage=None,
        )
        self.assertAlmostEqual(entry, 1.0, places=6)


class TestProtectionQtyCoverage(unittest.TestCase):
    def test_single_order_full_balance(self):
        orders = [{"quantity": "0.313", "order_status": "ACTIVE"}]
        self.assertTrue(_protection_quantities_cover_position(orders, 0.31311604))
        self.assertTrue(_quantity_matches_position(orders[0], 0.31311604))

    def test_multi_lot_sum_covers_aave_style(self):
        # Prod AAVE: three lot SL/TPs sum to wallet; each alone fails ±5%.
        orders = [
            {"quantity": "0.105", "order_status": "PENDING"},
            {"quantity": "0.104", "order_status": "PENDING"},
            {"quantity": "0.104", "order_status": "PENDING"},
        ]
        balance = 0.31311604
        self.assertTrue(_protection_quantities_cover_position(orders, balance))
        for o in orders:
            self.assertFalse(_quantity_matches_position(o, balance))

    def test_under_covered_multi_lot_is_not_protected(self):
        orders = [
            {"quantity": "0.10", "order_status": "ACTIVE"},
            {"quantity": "0.10", "order_status": "ACTIVE"},
        ]
        # 0.20 vs 0.313 → ~64% coverage, below 95% floor
        self.assertFalse(_protection_quantities_cover_position(orders, 0.31311604))

    def test_empty_orders_not_covered(self):
        self.assertFalse(_protection_quantities_cover_position([], 0.31))


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
    @patch("app.services.sl_tp_checker._find_recent_entry_order", return_value=None)
    @patch("app.services.sl_tp_checker._fetch_mark_price", return_value=0.0035)
    @patch.object(SLTPCheckerService, "_check_oco_issues", return_value={})
    @patch("app.services.sl_tp_checker.fetch_unified_open_orders")
    @patch("app.services.sl_tp_checker.trade_client")
    def test_detects_advanced_tp_without_sl(
        self, mock_trade, mock_fetch, _mock_oco, _mock_mark, _mock_entry
    ):
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

    @patch("app.services.sl_tp_checker._find_recent_entry_order", return_value=None)
    @patch("app.services.sl_tp_checker._fetch_mark_price", return_value=0.51)
    @patch.object(SLTPCheckerService, "_check_oco_issues", return_value={})
    @patch("app.services.sl_tp_checker.fetch_unified_open_orders")
    @patch("app.services.sl_tp_checker.trade_client")
    def test_skips_dust_positions(
        self, mock_trade, mock_fetch, _mock_oco, _mock_mark, _mock_entry
    ):
        # AKT dust: 0.05 * $0.51 ≈ $0.025 << $5
        mock_trade.get_account_summary.return_value = {
            "accounts": [{"currency": "AKT", "balance": "0.05"}]
        }
        mock_fetch.return_value = {
            "data_verified": True,
            "trigger_orders_status": "ok",
            "advanced_orders_status": "ok",
            "all_raw_orders": [],
        }
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        svc = SLTPCheckerService()
        result = svc.check_positions_for_sl_tp(db)

        self.assertEqual(result["positions_missing_sl_tp"], [])
        self.assertEqual(result["total_positions"], 0)

    @patch("app.services.sl_tp_checker._find_recent_entry_order", return_value=None)
    @patch("app.services.sl_tp_checker._fetch_mark_price", return_value=95.0)
    @patch.object(SLTPCheckerService, "_check_oco_issues", return_value={})
    @patch("app.services.sl_tp_checker.fetch_unified_open_orders")
    @patch("app.services.sl_tp_checker.trade_client")
    def test_multi_lot_aave_not_flagged_missing(
        self, mock_trade, mock_fetch, _mock_oco, _mock_mark, _mock_entry
    ):
        # Wallet fully covered by 3 SL + 3 TP lot legs; none alone matches balance.
        mock_trade.get_account_summary.return_value = {
            "accounts": [{"currency": "AAVE", "balance": "0.31311604"}]
        }
        legs = []
        for qty, oid_base in (("0.105", "1"), ("0.104", "2"), ("0.104", "3")):
            legs.append(
                {
                    "instrument_name": "AAVE_USD",
                    "order_type": "STOP_LIMIT",
                    "order_status": "PENDING",
                    "quantity": qty,
                    "order_id": f"sl-{oid_base}",
                    "side": "SELL",
                }
            )
            legs.append(
                {
                    "instrument_name": "AAVE_USD",
                    "order_type": "TAKE_PROFIT_LIMIT",
                    "order_status": "PENDING",
                    "quantity": qty,
                    "order_id": f"tp-{oid_base}",
                    "side": "SELL",
                }
            )
        mock_fetch.return_value = {
            "data_verified": True,
            "trigger_orders_status": "ok",
            "advanced_orders_status": "ok",
            "all_raw_orders": legs,
        }
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        svc = SLTPCheckerService()
        result = svc.check_positions_for_sl_tp(db)

        missing = result["positions_missing_sl_tp"]
        aave_missing = [m for m in missing if "AAVE" in str(m.get("symbol", ""))]
        self.assertEqual(aave_missing, [])


if __name__ == "__main__":
    unittest.main()
