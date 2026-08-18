"""Refuse BUY-side protection when the wallet holds no short (issue #496).

A SELL entry gets BUY-side SL/TP, which exists only to close a short. When the
FIFO turns an unmatchable sell into a phantom short lot, that BUY protection
gets armed and filled, and the bot buys inventory it never sold (ALGO_USD:
620,65 USD over 22 fills). The guard applies the system's own definition of a
short — negative base balance — at the single choke point every creation path
funnels through.
"""
import itertools
import unittest
from unittest.mock import MagicMock, patch

from app.services.tp_sl_order_creator import (
    matching_wallet_balances,
    short_cover_block_reason,
)


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


# --- the exchange's account ordering must never decide protection ------------


def _split_accounts(*entries):
    """Accounts as the exchange might serialise them, in the given order."""
    return {"accounts": [{"currency": c, "balance": b} for c, b in entries]}


class TestMultipleMatchingAccounts(unittest.TestCase):
    """_account_matches_symbol matches the bare base, the exact pair and ETH_*.

    So one symbol can map to several accounts. Reading only the first one made
    the verdict depend on the exchange's serialisation order, which can change
    without any deploy on our side.
    """

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_spot_first_then_margin_short_allows(self, mock_client):
        # Positive spot listed before the negative margin leg.
        mock_client.get_account_summary.return_value = _split_accounts(
            ("ETH", 1.5), ("ETH_SHORT", -0.75)
        )
        self.assertIsNone(short_cover_block_reason("ETH_USD", "SELL"))

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_margin_short_first_then_spot_allows(self, mock_client):
        # Same account set, opposite order. The verdict must not change.
        mock_client.get_account_summary.return_value = _split_accounts(
            ("ETH_SHORT", -0.75), ("ETH", 1.5)
        )
        self.assertIsNone(short_cover_block_reason("ETH_USD", "SELL"))

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_order_is_irrelevant_for_every_permutation(self, mock_client):
        """The property, stated directly: order must never change the verdict."""
        entries = [("ETH", 1.5), ("ETH_SHORT", -0.75), ("ETH_USD", 0.0)]
        verdicts = set()
        for permutation in itertools.permutations(entries):
            mock_client.get_account_summary.return_value = _split_accounts(*permutation)
            verdicts.add(short_cover_block_reason("ETH_USD", "SELL"))
        self.assertEqual(
            verdicts,
            {None},
            "a short exists in this account set; every ordering must allow",
        )

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_all_positive_still_blocks_in_any_order(self, mock_client):
        """No negative anywhere means no short — that verdict is order-proof too."""
        entries = [("ALGO", 1220.11), ("ALGO_USD", 71.11)]
        verdicts = set()
        for permutation in itertools.permutations(entries):
            mock_client.get_account_summary.return_value = _split_accounts(*permutation)
            reason = short_cover_block_reason("ALGO_USD", "SELL")
            self.assertIsNotNone(reason)
            verdicts.add("blocked")
        self.assertEqual(verdicts, {"blocked"})

    @patch("app.services.tp_sl_order_creator.trade_client")
    def test_unrelated_currencies_are_not_counted(self, mock_client):
        """A short on another asset must not license an ETH cover order."""
        mock_client.get_account_summary.return_value = _split_accounts(
            ("BTC", -2.0), ("ETH", 1.5)
        )
        reason = short_cover_block_reason("ETH_USD", "SELL")
        self.assertIsNotNone(reason)
        self.assertIn("1.5", reason)

    def test_matching_wallet_balances_collects_every_match(self):
        accounts = _split_accounts(
            ("ETH", 1.5), ("ETH_SHORT", -0.75), ("BTC", 9.0)
        )["accounts"]
        self.assertEqual(
            sorted(matching_wallet_balances(accounts, "ETH_USD")), [-0.75, 1.5]
        )

    def test_matching_wallet_balances_survives_junk_rows(self):
        accounts = [
            {"currency": "ETH", "balance": "not-a-number"},
            {"currency": "ETH_SHORT", "balance": -0.75},
            {"currency": None, "balance": 1},
        ]
        self.assertEqual(matching_wallet_balances(accounts, "ETH_USD"), [-0.75])
