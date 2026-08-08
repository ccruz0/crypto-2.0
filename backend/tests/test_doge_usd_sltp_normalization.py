"""
Tests for DOGE_USD SL/TP quantity normalization fallbacks.

Regression: order 5755600491448633454 (130 DOGE) failed SL/TP with
Step_size=None, minQty=None, strategies_tried=[] when instrument metadata
was unavailable.
"""

import unittest
from unittest.mock import patch

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.brokers.crypto_com_trade import CryptoComTradeClient


class TestInstrumentSymbolCandidates(unittest.TestCase):
    def test_usd_usdt_variants(self):
        candidates = CryptoComTradeClient._instrument_symbol_candidates("DOGE_USD")
        self.assertIn("DOGE_USD", candidates)
        self.assertIn("DOGE_USDT", candidates)

    def test_dedupes(self):
        candidates = CryptoComTradeClient._instrument_symbol_candidates("BTC_USDT")
        self.assertEqual(len(candidates), len(set(candidates)))


class TestInferSlTpQuantityMetadata(unittest.TestCase):
    def test_whole_number_doge_like(self):
        meta = CryptoComTradeClient._infer_sl_tp_quantity_metadata(130.0)
        self.assertEqual(meta["qty_tick_size"], "1")
        self.assertEqual(meta["quantity_decimals"], 0)
        self.assertTrue(meta.get("inferred"))

    def test_fractional_quantity(self):
        meta = CryptoComTradeClient._infer_sl_tp_quantity_metadata(6.425)
        self.assertIn("qty_tick_size", meta)
        self.assertTrue(meta.get("inferred"))


class TestNormalizeSafeWithInferredFallback(unittest.TestCase):
    def setUp(self):
        self.client = CryptoComTradeClient()
        self.client._instrument_cache = {}

    @patch.object(CryptoComTradeClient, "_get_instrument_metadata", return_value=None)
    def test_doge_130_normalizes_with_inferred_metadata(self, _mock_meta):
        qty_str, diag = self.client.normalize_quantity_safe_with_fallback(
            symbol="DOGE_USD",
            raw_quantity=130.0,
            for_sl_tp=True,
        )
        self.assertEqual(qty_str, "130")
        self.assertIn("inferred_metadata", diag["strategies_tried"])
        self.assertIn("standard", diag["strategies_tried"])
        self.assertEqual(diag["final_reason"], "standard_success")

    @patch.object(CryptoComTradeClient, "_get_instrument_metadata", return_value=None)
    def test_non_sltp_still_blocks_without_metadata(self, _mock_meta):
        qty_str, diag = self.client.normalize_quantity_safe_with_fallback(
            symbol="DOGE_USD",
            raw_quantity=130.0,
            for_sl_tp=False,
        )
        self.assertIsNone(qty_str)
        self.assertEqual(diag["final_reason"], "instrument_rules_unavailable")


class TestInstrumentMetadataVariantLookup(unittest.TestCase):
    def setUp(self):
        self.client = CryptoComTradeClient()
        self.client._instrument_cache = {}

    @patch("app.services.brokers.crypto_com_trade.http_get")
    def test_resolves_usd_via_usdt_variant(self, mock_http_get):
        mock_http_get.return_value.json.return_value = {
            "result": {
                "data": [
                    {
                        "symbol": "DOGE_USDT",
                        "qty_tick_size": "1",
                        "quantity_decimals": 0,
                        "min_quantity": "1",
                        "price_decimals": 5,
                        "price_tick_size": "0.00001",
                    }
                ]
            }
        }
        mock_http_get.return_value.raise_for_status = lambda: None

        meta = self.client._get_instrument_metadata("DOGE_USD")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["qty_tick_size"], "1")
        self.assertEqual(meta["quantity_decimals"], 0)
        # Cached under requested symbol too
        self.assertIsNotNone(self.client._instrument_cache.get("DOGE_USD"))


if __name__ == "__main__":
    unittest.main()
