"""Refuse BUY-side protection when the wallet holds no short (issue #496).

A SELL entry gets BUY-side SL/TP, which exists only to close a short. When the
FIFO turns an unmatchable sell into a phantom short lot, that BUY protection
gets armed and filled, and the bot buys inventory it never sold (ALGO_USD:
620,65 USD over 22 fills). The guard applies the system's own definition of a
short — negative base balance — at the single choke point every creation path
funnels through.
"""
import unittest
from unittest.mock import MagicMock, patch

from app.services.tp_sl_order_creator import short_cover_block_reason


def _accounts(balance):
    return {"accounts": [{"currency": "ALGO", "balance": balance}]}


class TestShortCoverBlockReason(unittest.TestCase):
    """The predicate itself: when does a SELL entry lose its protection?"""

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_positive_wallet_blocks_short_cover(self, mock_client):
        mock_client.get_account_summary.return_value = _accounts(1220.1149)
        reason = short_cover_block_reason("ALGO_USD", "SELL")
        self.assertIsNotNone(reason)
        self.assertIn("no short to cover", reason)

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_zero_wallet_blocks_short_cover(self, mock_client):
        # Flat is not short. Nothing to buy back.
        mock_client.get_account_summary.return_value = _accounts(0)
        self.assertIsNotNone(short_cover_block_reason("ALGO_USD", "SELL"))

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_negative_wallet_allows_real_short(self, mock_client):
        mock_client.get_account_summary.return_value = _accounts(-500.0)
        self.assertIsNone(short_cover_block_reason("ALGO_USD", "SELL"))

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_buy_entry_never_blocked(self, mock_client):
        # Long protection is SELL-side and has nothing to do with this guard.
        mock_client.get_account_summary.return_value = _accounts(1220.1149)
        self.assertIsNone(short_cover_block_reason("ALGO_USD", "BUY"))
        mock_client.get_account_summary.assert_not_called()

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_dry_run_never_blocked(self, mock_client):
        mock_client.get_account_summary.return_value = _accounts(1220.1149)
        self.assertIsNone(
            short_cover_block_reason("ALGO_USD", "SELL", dry_run=True)
        )
        mock_client.get_account_summary.assert_not_called()

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_wallet_error_fails_open(self, mock_client):
        # Leaving a real short unprotected is worse than one phantom cover.
        mock_client.get_account_summary.side_effect = RuntimeError("API down")
        self.assertIsNone(short_cover_block_reason("ALGO_USD", "SELL"))

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_unknown_currency_fails_open(self, mock_client):
        mock_client.get_account_summary.return_value = {"accounts": []}
        self.assertIsNone(short_cover_block_reason("ALGO_USD", "SELL"))


class TestCreatorsHonourGuard(unittest.TestCase):
    """The three creation entrypoints must refuse before touching the exchange."""

    def setUp(self):
        self.db = MagicMock()

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_take_profit_blocked_on_positive_wallet(self, mock_client):
        from app.services.tp_sl_order_creator import create_take_profit_order

        mock_client.get_account_summary.return_value = _accounts(1220.1149)
        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=None,
        ):
            res = create_take_profit_order(
                db=self.db,
                symbol="ALGO_USD",
                side="SELL",
                tp_price=0.0799,
                quantity=1258.0,
                entry_price=0.0813,
                parent_order_id="5755600486727374908",
            )
        self.assertIsNone(res.get("order_id"))
        self.assertIn("no short to cover", res.get("error") or "")
        mock_client.create_order.assert_not_called()

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_stop_loss_blocked_on_positive_wallet(self, mock_client):
        from app.services.tp_sl_order_creator import create_stop_loss_order

        mock_client.get_account_summary.return_value = _accounts(1220.1149)
        res = create_stop_loss_order(
            db=self.db,
            symbol="ALGO_USD",
            side="SELL",
            sl_price=0.0838,
            quantity=1258.0,
            entry_price=0.0813,
            parent_order_id="5755600486727374908",
        )
        self.assertIsNone(res.get("order_id"))
        self.assertIn("no short to cover", res.get("error") or "")
        mock_client.create_order.assert_not_called()

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_native_oco_blocked_on_positive_wallet(self, mock_client):
        from app.services.tp_sl_order_creator import create_oco_protection_orders

        mock_client.get_account_summary.return_value = _accounts(1220.1149)
        with patch(
            "app.services.sl_tp_protection.get_active_protection_order",
            return_value=None,
        ):
            res = create_oco_protection_orders(
                db=self.db,
                symbol="ALGO_USD",
                side="SELL",
                tp_price=0.0799,
                sl_price=0.0838,
                quantity=1258.0,
                entry_price=0.0813,
                parent_order_id="5755600486727374908",
            )
        self.assertIsNone(res["sl_result"]["order_id"])
        self.assertIsNone(res["tp_result"]["order_id"])
        self.assertIn("no short to cover", res.get("error") or "")
        mock_client.create_order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
