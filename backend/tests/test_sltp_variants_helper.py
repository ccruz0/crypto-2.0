"""
Unit-style tests for the SL/TP variants helper (format-only utilities).
"""

import unittest
import sys
import os
from decimal import Decimal

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.brokers.crypto_com_trade import CryptoComTradeClient


class TestSLTPVariantsHelper(unittest.TestCase):
    def setUp(self):
        self.client = CryptoComTradeClient()

    def test_normalize_price_str_plain_decimal(self):
        n = self.client._normalize_price_str

        self.assertEqual(n(2954.86), "2954.86")
        self.assertEqual(n("2954.860000"), "2954.86")
        self.assertEqual(n(Decimal("10.0000")), "10")
        self.assertEqual(n(Decimal("0.0033000")), "0.0033")
        self.assertEqual(n(Decimal("0E-8")), "0")
        self.assertEqual(n("1e-7"), "0.0000001")

    def test_build_sltp_variant_grid_bounded_and_contains_types(self):
        variants = self.client._build_sltp_variant_grid(max_variants=240)
        # max_variants is a per-order-type cap; total can be up to 2x.
        self.assertLessEqual(len(variants), 480)

        types = {v.get("order_type") for v in variants}
        self.assertIn("STOP_LIMIT", types)
        self.assertIn("TAKE_PROFIT_LIMIT", types)

        # Sanity: required keys exist
        sample = variants[0]
        self.assertIn("variant_id", sample)
        self.assertIn("trigger_key", sample)
        self.assertIn("value_type", sample)


if __name__ == "__main__":
    unittest.main()

