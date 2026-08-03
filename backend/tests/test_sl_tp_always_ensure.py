"""Tests for indicator formatting and always-on SL/TP ensure."""

import unittest
from unittest.mock import MagicMock, patch

from app.utils.indicator_format import format_indicator_value
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.sl_tp_checker import (
    SLTPCheckerService,
    _classify_open_protection_leg,
    _db_protection_covers_wallet,
    _derive_entry_from_abs_prices,
    _entry_symbol_variants,
    _heal_half_protected_tp_parents,
    _is_expected_ensure_skip,
    _iter_half_protected_entry_parents,
    _order_entry_price,
    _parent_lot_qty,
    _protection_create_qty,
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


class TestProtectionCreateQty(unittest.TestCase):
    def test_linked_parent_uses_lot_not_wallet(self):
        parent = MagicMock(cumulative_quantity=0.3, quantity=0.3)
        self.assertAlmostEqual(
            _protection_create_qty(position_balance=1.893, parent_order=parent),
            0.3,
        )

    def test_no_parent_uses_wallet(self):
        self.assertAlmostEqual(
            _protection_create_qty(position_balance=1.893, parent_order=None),
            1.893,
        )

    def test_parent_larger_than_wallet_caps_to_wallet(self):
        parent = MagicMock(cumulative_quantity=2.0, quantity=2.0)
        self.assertAlmostEqual(
            _protection_create_qty(position_balance=1.5, parent_order=parent),
            1.5,
        )

    def test_parent_lot_qty_prefers_cumulative(self):
        parent = MagicMock(cumulative_quantity=0.25, quantity=0.3)
        self.assertAlmostEqual(_parent_lot_qty(parent), 0.25)


class TestDbSisterBookCoverage(unittest.TestCase):
    def test_sister_tps_cover_wallet(self):
        db = MagicMock()
        rows = [
            MagicMock(quantity=1.3, cumulative_quantity=1.3),
            MagicMock(quantity=0.3, cumulative_quantity=0.3),
            MagicMock(quantity=0.3, cumulative_quantity=0.3),
        ]
        db.query.return_value.filter.return_value.all.return_value = rows
        self.assertTrue(
            _db_protection_covers_wallet(
                db, ["BTC_USDT", "BTC_USD"], "TAKE_PROFIT", 1.893
            )
        )

    def test_under_covered_sister_tps(self):
        db = MagicMock()
        rows = [MagicMock(quantity=0.3, cumulative_quantity=0.3)]
        db.query.return_value.filter.return_value.all.return_value = rows
        self.assertFalse(
            _db_protection_covers_wallet(
                db, ["BTC_USDT", "BTC_USD"], "TAKE_PROFIT", 1.893
            )
        )


class TestEnsureMissingProtection(unittest.TestCase):
    @patch.object(SLTPCheckerService, "_ensure_multilot_tp_heal")
    @patch.object(SLTPCheckerService, "_create_protection_order")
    @patch.object(SLTPCheckerService, "check_positions_for_sl_tp")
    def test_auto_creates_only_missing_leg(
        self, mock_check, mock_create, mock_multilot
    ):
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
        mock_multilot.assert_not_called()
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(result["still_missing"], [])
        self.assertEqual(result.get("skipped"), [])

    @patch.object(
        SLTPCheckerService,
        "_ensure_multilot_tp_heal",
        return_value={"healed": [], "skipped": [], "failed": []},
    )
    @patch.object(SLTPCheckerService, "_create_protection_order")
    @patch.object(SLTPCheckerService, "check_positions_for_sl_tp")
    def test_wallet_side_mismatch_is_skipped_not_failed(
        self, mock_check, mock_create, _mock_multilot
    ):
        """Hourly Telegram must not page expected wallet_side_mismatch skips."""
        svc = SLTPCheckerService()
        mock_check.return_value = {
            "positions_missing_sl_tp": [
                {
                    "symbol": "BTC_USD",
                    "currency": "BTC",
                    "balance": 0.05,
                    "has_sl": False,
                    "has_tp": False,
                    "sl_price": None,
                    "tp_price": None,
                    "skip_reminder": False,
                }
            ],
            "total_positions": 1,
            "oco_issues": {},
            "checked_at": None,
        }
        mock_create.return_value = {
            "success": False,
            "error": "wallet_side_mismatch: fill=SELL wallet=BUY",
            "sl_order_id": None,
            "tp_order_id": None,
        }

        result = svc.ensure_missing_protection(MagicMock())

        self.assertEqual(result["failed"], [])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertIn("wallet_side_mismatch", result["skipped"][0]["skip_reason"])
        self.assertEqual(result["created"], [])

    @patch.object(SLTPCheckerService, "_ensure_multilot_tp_heal")
    @patch.object(SLTPCheckerService, "_create_protection_order")
    @patch.object(SLTPCheckerService, "check_positions_for_sl_tp")
    def test_multilot_tp_heal_runs_when_tp_missing(
        self, mock_check, mock_create, mock_multilot
    ):
        """AAVE-style: recent parent ensure ok, older SL-only lots still healed."""
        svc = SLTPCheckerService()
        mock_check.return_value = {
            "positions_missing_sl_tp": [
                {
                    "symbol": "AAVE_USD",
                    "currency": "AAVE",
                    "balance": 0.518,
                    "has_sl": True,
                    "has_tp": False,
                    "sl_price": None,
                    "tp_price": None,
                    "skip_reminder": False,
                    "watchlist_item": None,
                }
            ],
            "total_positions": 1,
            "oco_issues": {},
            "checked_at": None,
        }
        mock_create.return_value = {
            "success": True,
            "sl_order_id": "sl-recent",
            "tp_order_id": "tp-recent",
            "status": "already_protected",
        }
        mock_multilot.return_value = {
            "healed": [
                {
                    "parent_order_id": "5755600492313745241",
                    "sl_order_id": "sl-old",
                    "tp_order_id": "tp-new",
                    "oco_group_id": "oco_new",
                    "status": "oco_created",
                }
            ],
            "skipped": [],
            "failed": [],
        }

        result = svc.ensure_missing_protection(MagicMock())

        mock_multilot.assert_called_once()
        self.assertEqual(len(result["healed_parents"]), 1)
        self.assertEqual(
            result["healed_parents"][0]["parent_order_id"], "5755600492313745241"
        )
        self.assertTrue(
            any(c.get("source") == "multilot_tp_heal" for c in result["created"])
        )


class TestHalfProtectedMultilotHeal(unittest.TestCase):
    def test_iter_half_protected_keeps_sl_only_parents(self):
        older = MagicMock(spec=ExchangeOrder)
        older.exchange_order_id = "parent-old"
        older.symbol = "AAVE_USD"
        older.side = OrderSideEnum.BUY
        older.status = OrderStatusEnum.FILLED
        older.order_role = None
        older.quantity = 0.103
        older.cumulative_quantity = 0.103
        older.avg_price = 96.812
        older.exchange_create_time = None

        recent = MagicMock(spec=ExchangeOrder)
        recent.exchange_order_id = "parent-new"
        recent.symbol = "AAVE_USD"
        recent.side = OrderSideEnum.BUY
        recent.status = OrderStatusEnum.FILLED
        recent.order_role = None

        db = MagicMock()
        query = MagicMock()
        db.query.return_value = query
        query.filter.return_value = query
        query.order_by.return_value = query
        query.all.return_value = [recent, older]

        def _active(_db, parent_id, role):
            if parent_id == "parent-old" and role == "STOP_LOSS":
                return MagicMock()
            if parent_id == "parent-old" and role == "TAKE_PROFIT":
                return None
            if parent_id == "parent-new" and role in ("STOP_LOSS", "TAKE_PROFIT"):
                return MagicMock()
            return None

        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            side_effect=_active,
        ):
            half = _iter_half_protected_entry_parents(
                db, "AAVE_USD", entry_side="BUY"
            )

        self.assertEqual([p.exchange_order_id for p in half], ["parent-old"])

    @patch("app.services.sl_tp_checker._fetch_mark_price", return_value=91.43)
    def test_heal_calls_native_oco_per_half_protected_parent(self, _mock_mark):
        parent = MagicMock(spec=ExchangeOrder)
        parent.exchange_order_id = "5755600492313745241"
        parent.symbol = "AAVE_USD"
        parent.side = OrderSideEnum.BUY
        parent.avg_price = 96.812
        parent.quantity = 0.103
        parent.cumulative_quantity = 0.103
        parent.price = 96.812
        parent.cumulative_value = None

        sl = MagicMock(spec=ExchangeOrder)
        sl.exchange_order_id = "sl-old"
        sl.order_role = "STOP_LOSS"

        db = MagicMock()
        with patch(
            "app.services.sl_tp_checker._iter_half_protected_entry_parents",
            return_value=[parent],
        ), patch(
            "app.services.sl_tp_protection.should_skip_rejected_tp_backfill",
            return_value=False,
        ), patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            side_effect=lambda _db, _pid, role: sl if role == "STOP_LOSS" else None,
        ), patch(
            "app.services.tp_sl_order_creator.is_native_oco_enabled",
            return_value=True,
        ), patch(
            "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
            return_value=(False, None),
        ), patch(
            "app.services.tp_sl_order_creator.ensure_spot_oco_protection",
            return_value={
                "sl_result": {"order_id": "sl-new"},
                "tp_result": {"order_id": "tp-new"},
                "oco_group_id": "oco-1",
                "error": None,
                "status": "oco_created",
            },
        ) as mock_oco:
            result = _heal_half_protected_tp_parents(
                db,
                "AAVE_USD",
                position_balance=0.518,
                entry_side="BUY",
                sl_percentage=10.0,
                tp_percentage=1.0,
                dry_run=False,
            )

        mock_oco.assert_called_once()
        kwargs = mock_oco.call_args.kwargs
        self.assertEqual(kwargs["parent_order_id"], "5755600492313745241")
        self.assertAlmostEqual(float(kwargs["quantity"]), 0.103)
        self.assertEqual(len(result["healed"]), 1)
        self.assertEqual(result["healed"][0]["tp_order_id"], "tp-new")

    @patch("app.services.sl_tp_checker._fetch_mark_price", return_value=91.43)
    def test_heal_skips_margin_rejected_terminal(self, _mock_mark):
        parent = MagicMock(spec=ExchangeOrder)
        parent.exchange_order_id = "parent-margin"
        parent.avg_price = 96.0
        parent.quantity = 0.1
        parent.cumulative_quantity = 0.1
        parent.price = 96.0
        parent.cumulative_value = None
        parent.side = OrderSideEnum.BUY

        db = MagicMock()
        with patch(
            "app.services.sl_tp_checker._iter_half_protected_entry_parents",
            return_value=[parent],
        ), patch(
            "app.services.sl_tp_protection.should_skip_rejected_tp_backfill",
            return_value=True,
        ), patch(
            "app.services.tp_sl_order_creator.ensure_spot_oco_protection"
        ) as mock_oco:
            result = _heal_half_protected_tp_parents(
                db,
                "AAVE_USD",
                position_balance=0.1,
                entry_side="BUY",
                sl_percentage=10.0,
                tp_percentage=1.0,
                dry_run=False,
            )

        mock_oco.assert_not_called()
        self.assertEqual(result["healed"], [])
        self.assertEqual(result["skipped"][0]["reason"], "tp_rejected_terminal")


class TestExpectedEnsureSkip(unittest.TestCase):
    def test_wallet_side_mismatch_error(self):
        self.assertTrue(
            _is_expected_ensure_skip(
                {"error": "wallet_side_mismatch: fill=SELL wallet=BUY"}
            )
        )

    def test_tp_rejected_terminal_skip_reason(self):
        self.assertTrue(
            _is_expected_ensure_skip(
                {"success": True, "skip_reason": "tp_rejected_terminal"}
            )
        )

    def test_real_failure_not_skipped(self):
        self.assertFalse(
            _is_expected_ensure_skip({"error": "Both SL and TP orders failed"})
        )


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
    @patch("app.services.sl_tp_checker._fetch_mark_price", return_value=0.55)
    @patch.object(SLTPCheckerService, "_check_oco_issues", return_value={})
    @patch("app.services.sl_tp_checker.fetch_unified_open_orders")
    @patch("app.services.sl_tp_checker.trade_client")
    def test_includes_short_wallet_missing_tp(
        self, mock_trade, mock_fetch, _mock_oco, _mock_mark, _mock_entry
    ):
        """Negative wallets are SHORT positions — must enter ensure/REVISIÓN path."""
        mock_trade.get_account_summary.return_value = {
            "accounts": [
                {
                    "currency": "APT",
                    "quantity": "-17.661",
                    "balance": "-17.661",
                    "market_value": "-9.85",
                }
            ]
        }
        mock_fetch.return_value = {
            "data_verified": True,
            "trigger_orders_status": "ok",
            "advanced_orders_status": "ok",
            "all_raw_orders": [
                {
                    "instrument_name": "APT_USD",
                    "order_type": "STOP_LIMIT",
                    "order_status": "ACTIVE",
                    "quantity": "17.661",
                    "order_id": "sl-short-1",
                    "side": "BUY",
                }
            ],
        }
        db = MagicMock()
        # Prefer APT_USD watchlist / entry pair resolution
        wl = MagicMock()
        wl.symbol = "APT_USD"
        wl.skip_sl_tp_reminder = False
        wl.sl_price = None
        wl.tp_price = None
        db.query.return_value.filter.return_value.first.return_value = wl

        svc = SLTPCheckerService()
        result = svc.check_positions_for_sl_tp(db)

        missing = result["positions_missing_sl_tp"]
        self.assertEqual(len(missing), 1)
        self.assertIn("APT", str(missing[0]["symbol"]))
        self.assertLess(float(missing[0]["balance"]), 0)
        self.assertTrue(missing[0]["has_sl"])
        self.assertFalse(missing[0]["has_tp"])
        self.assertEqual(result["total_positions"], 1)

    @patch.object(
        SLTPCheckerService,
        "_ensure_multilot_tp_heal",
        return_value={"healed": [], "skipped": [], "failed": []},
    )
    @patch.object(SLTPCheckerService, "_create_protection_order")
    @patch.object(SLTPCheckerService, "check_positions_for_sl_tp")
    def test_ensure_creates_missing_tp_for_short(
        self, mock_check, mock_create, mock_multilot
    ):
        svc = SLTPCheckerService()
        mock_check.return_value = {
            "positions_missing_sl_tp": [
                {
                    "symbol": "DOGE_USD",
                    "currency": "DOGE",
                    "balance": -845.19,
                    "has_sl": True,
                    "has_tp": False,
                    "sl_price": None,
                    "tp_price": None,
                    "skip_reminder": False,
                }
            ],
            "total_positions": 1,
            "oco_issues": {},
            "checked_at": None,
        }
        mock_create.return_value = {
            "success": True,
            "sl_order_id": None,
            "tp_order_id": "tp-short-1",
        }

        result = svc.ensure_missing_protection(MagicMock())

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        self.assertFalse(kwargs["create_sl"])
        self.assertTrue(kwargs["create_tp"])
        self.assertTrue(kwargs["force"])
        mock_multilot.assert_called_once()
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(result["still_missing"], [])

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
