"""
Margin info lookup: bare base symbols must resolve to quote pairs.

Regression: watchlist stored ALGO (no quote). Exact-match lookup returned
margin_trading_enabled=False → decide_trading_mode forced SPOT →
INSUFFICIENT_FUNDS (306). Live instruments ALGO_USD / ALGO_USDT both have
margin enabled.
"""
import unittest
from unittest.mock import patch

from app.services.margin_info_service import MarginInfoService


def _algo_usd_instrument():
    return {
        "symbol": "ALGO_USD",
        "margin_buy_enabled": True,
        "margin_sell_enabled": True,
        "max_leverage": "50",
    }


def _btc_usd_instrument():
    return {
        "symbol": "BTC_USD",
        "margin_buy_enabled": True,
        "margin_sell_enabled": True,
        "max_leverage": "10",
    }


class TestSymbolLookupCandidates(unittest.TestCase):
    def test_bare_base_prefers_usd_then_usdt(self):
        self.assertEqual(
            MarginInfoService._symbol_lookup_candidates("ALGO"),
            ["ALGO", "ALGO_USD", "ALGO_USDT"],
        )

    def test_paired_symbol_exact_only(self):
        self.assertEqual(
            MarginInfoService._symbol_lookup_candidates("ALGO_USDT"),
            ["ALGO_USDT"],
        )
        self.assertEqual(
            MarginInfoService._symbol_lookup_candidates("BTC_USD"),
            ["BTC_USD"],
        )


class TestGetMarginInfoBaseSymbol(unittest.TestCase):
    def setUp(self):
        self.svc = MarginInfoService()
        self.svc.clear_cache()

    @patch.object(MarginInfoService, "_fetch_all_instruments")
    def test_bare_algo_resolves_to_margin_enabled_pair(self, mock_fetch):
        mock_fetch.return_value = [_algo_usd_instrument(), _btc_usd_instrument()]

        info = self.svc.get_margin_info_for_symbol("ALGO")

        self.assertTrue(info.margin_trading_enabled)
        self.assertEqual(info.max_leverage, 50.0)
        self.assertEqual(info.instrument_name, "ALGO_USD")
        # Cached under requested key
        self.assertIn("ALGO", self.svc._cache)
        cached = self.svc.get_margin_info_for_symbol("ALGO")
        self.assertTrue(cached.margin_trading_enabled)
        # Second call should not re-fetch while cache is warm
        self.assertEqual(mock_fetch.call_count, 1)

    @patch.object(MarginInfoService, "_fetch_all_instruments")
    def test_paired_symbol_exact_matches(self, mock_fetch):
        mock_fetch.return_value = [_algo_usd_instrument(), _btc_usd_instrument()]

        info = self.svc.get_margin_info_for_symbol("BTC_USD")

        self.assertTrue(info.margin_trading_enabled)
        self.assertEqual(info.max_leverage, 10.0)
        self.assertEqual(info.instrument_name, "BTC_USD")

    @patch.object(MarginInfoService, "_fetch_all_instruments")
    def test_unknown_base_returns_no_margin_default(self, mock_fetch):
        mock_fetch.return_value = [_btc_usd_instrument()]

        info = self.svc.get_margin_info_for_symbol("NOCOIN")

        self.assertFalse(info.margin_trading_enabled)
        self.assertIsNone(info.max_leverage)
        self.assertEqual(info.instrument_name, "NOCOIN")

    @patch.object(MarginInfoService, "_fetch_all_instruments")
    def test_paired_unknown_does_not_try_quote_variants(self, mock_fetch):
        """ALGO_EUR must not fall back to ALGO_USD — only bare bases expand."""
        mock_fetch.return_value = [_algo_usd_instrument()]

        info = self.svc.get_margin_info_for_symbol("ALGO_EUR")

        self.assertFalse(info.margin_trading_enabled)
        self.assertEqual(info.instrument_name, "ALGO_EUR")


if __name__ == "__main__":
    unittest.main()
