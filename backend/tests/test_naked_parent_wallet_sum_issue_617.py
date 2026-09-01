"""Issue #617: skip naked FIFO parent alerts when wallet-sum SL+TP already covers."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.sl_tp_checker import (
    SLTPCheckerService,
    _wallet_sum_covers_sl_tp,
)


class TestWalletSumCoversPredicate(unittest.TestCase):
    def test_both_legs_required(self):
        self.assertTrue(_wallet_sum_covers_sl_tp(True, True))
        self.assertFalse(_wallet_sum_covers_sl_tp(True, False))
        self.assertFalse(_wallet_sum_covers_sl_tp(False, True))
        self.assertFalse(_wallet_sum_covers_sl_tp(False, False))


def _naked_apt_parent():
    parent = ExchangeOrder(
        exchange_order_id="5755600492526823562",
        symbol="APT_USD",
        side=OrderSideEnum.SELL,
        status=OrderStatusEnum.FILLED,
        order_role=None,
        quantity=17.65,
        cumulative_quantity=17.65,
        avg_price=4.5,
        exchange_create_time=datetime(2025, 8, 2, tzinfo=timezone.utc),
        exchange_update_time=datetime(2025, 8, 2, tzinfo=timezone.utc),
    )
    return parent


class TestCheckPositionsWalletSumNakedParents(unittest.TestCase):
    @patch("app.services.sl_tp_checker._find_recent_entry_order", return_value=None)
    @patch("app.services.sl_tp_checker._fetch_mark_price", return_value=4.5)
    @patch.object(SLTPCheckerService, "_check_oco_issues", return_value={})
    @patch("app.services.sl_tp_checker._iter_naked_entry_parents")
    @patch("app.services.sl_tp_checker.fetch_unified_open_orders")
    @patch("app.services.sl_tp_checker.trade_client")
    def test_skips_naked_parents_when_wallet_sum_covers(
        self,
        mock_trade,
        mock_fetch,
        mock_naked_iter,
        _mock_oco,
        _mock_mark,
        _mock_entry,
    ):
        """APT/BTC ghost FIFO parents must not alert when SL+TP sum covers wallet."""
        wallet = -173.49
        mock_trade.get_account_summary.return_value = {
            "accounts": [{"currency": "APT", "balance": str(wallet)}]
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
                    "quantity": "173.49",
                    "order_id": "sl-apt-live",
                    "side": "BUY",
                },
                {
                    "instrument_name": "APT_USD",
                    "order_type": "TAKE_PROFIT_LIMIT",
                    "order_status": "ACTIVE",
                    "quantity": "173.49",
                    "order_id": "tp-apt-live",
                    "side": "BUY",
                },
            ],
        }
        mock_naked_iter.return_value = [_naked_apt_parent()]

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = SLTPCheckerService().check_positions_for_sl_tp(db)

        self.assertEqual(result["positions_missing_sl_tp"], [])
        self.assertEqual(result["naked_entry_parent_count"], 0)
        mock_naked_iter.assert_not_called()

    @patch("app.services.sl_tp_checker._find_recent_entry_order", return_value=None)
    @patch("app.services.sl_tp_checker._fetch_mark_price", return_value=4.5)
    @patch.object(SLTPCheckerService, "_check_oco_issues", return_value={})
    @patch("app.services.sl_tp_checker._naked_parent_report_row")
    @patch("app.services.sl_tp_checker._iter_naked_entry_parents")
    @patch("app.services.sl_tp_checker.fetch_unified_open_orders")
    @patch("app.services.sl_tp_checker.trade_client")
    def test_keeps_naked_parents_when_wallet_missing_tp(
        self,
        mock_trade,
        mock_fetch,
        mock_naked_iter,
        mock_report_row,
        _mock_oco,
        _mock_mark,
        _mock_entry,
    ):
        """Half-protected wallet still surfaces naked parents (BONK SL-only gap)."""
        wallet = -173.49
        mock_trade.get_account_summary.return_value = {
            "accounts": [{"currency": "APT", "balance": str(wallet)}]
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
                    "quantity": "173.49",
                    "order_id": "sl-apt-live",
                    "side": "BUY",
                }
            ],
        }
        mock_naked_iter.return_value = [_naked_apt_parent()]
        mock_report_row.return_value = {
            "symbol": "APT_USD",
            "naked_parent": True,
            "order_id": "5755600492526823562",
            "has_sl": False,
            "has_tp": False,
        }

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with patch(
            "app.services.expected_take_profit.rebuild_open_lots", return_value=[]
        ):
            result = SLTPCheckerService().check_positions_for_sl_tp(db)

        mock_naked_iter.assert_called_once()
        missing = result["positions_missing_sl_tp"]
        self.assertEqual(len(missing), 1)
        self.assertTrue(missing[0].get("naked_parent"))


if __name__ == "__main__":
    unittest.main()
