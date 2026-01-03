"""
Unit tests for quantity normalization in Crypto.com Exchange orders.

Tests the normalize_quantity helper function to ensure it:
1. Rounds DOWN to the allowed step size (qty_tick_size)
2. Formats to exact quantity_decimals decimal places
3. Ensures quantity >= min_quantity (returns None if below)
4. Returns quantity as string (never float, never scientific notation)
"""

import unittest
from unittest.mock import Mock, patch
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.brokers.crypto_com_trade import CryptoComTradeClient


class TestQuantityNormalization(unittest.TestCase):
    """Test cases for normalize_quantity function"""
    
    def setUp(self):
        """Set up test client"""
        self.client = CryptoComTradeClient()
        # Clear cache before each test
        self.client._instrument_cache = {}
    
    def test_near_usdt_step_01_quantity_decimals_1(self):
        """Test NEAR_USDT: step=0.1, quantity_decimals=1, qty=6.42508353 -> 6.4"""
        # Mock instrument metadata for NEAR_USDT
        with patch.object(self.client, '_get_instrument_metadata', return_value={
            'quantity_decimals': 1,
            'qty_tick_size': '0.1',
            'min_quantity': '0.1'
        }):
            result = self.client.normalize_quantity('NEAR_USDT', 6.42508353)
            self.assertEqual(result, '6.4')
            self.assertIsInstance(result, str)
    
    def test_step_0001_quantity_decimals_4(self):
        """Test with step=0.0001, quantity_decimals=4, qty=6.42508353 -> 6.4250"""
        with patch.object(self.client, '_get_instrument_metadata', return_value={
            'quantity_decimals': 4,
            'qty_tick_size': '0.0001',
            'min_quantity': '0.001'
        }):
            result = self.client.normalize_quantity('TEST_USDT', 6.42508353)
            self.assertEqual(result, '6.4250')
            self.assertIsInstance(result, str)
    
    def test_step_001_quantity_decimals_2(self):
        """Test with step=0.01, quantity_decimals=2, qty=6.42508353 -> 6.42"""
        with patch.object(self.client, '_get_instrument_metadata', return_value={
            'quantity_decimals': 2,
            'qty_tick_size': '0.01',
            'min_quantity': '0.01'
        }):
            result = self.client.normalize_quantity('TEST_USDT', 6.42508353)
            self.assertEqual(result, '6.42')
            self.assertIsInstance(result, str)
    
    def test_round_down_never_rounds_up(self):
        """Test that rounding always rounds DOWN (never up)"""
        with patch.object(self.client, '_get_instrument_metadata', return_value={
            'quantity_decimals': 1,
            'qty_tick_size': '0.1',
            'min_quantity': '0.1'
        }):
            # 6.49 should round DOWN to 6.4, not up to 6.5
            result = self.client.normalize_quantity('TEST_USDT', 6.49)
            self.assertEqual(result, '6.4')
    
    def test_below_min_quantity_returns_none(self):
        """Test that quantity below min_quantity returns None"""
        with patch.object(self.client, '_get_instrument_metadata', return_value={
            'quantity_decimals': 1,
            'qty_tick_size': '0.1',
            'min_quantity': '1.0'  # Min is 1.0
        }):
            result = self.client.normalize_quantity('TEST_USDT', 0.5)
            self.assertIsNone(result)
    
    def test_exact_min_quantity_returns_formatted(self):
        """Test that exact min_quantity is returned (not None)"""
        with patch.object(self.client, '_get_instrument_metadata', return_value={
            'quantity_decimals': 1,
            'qty_tick_size': '0.1',
            'min_quantity': '1.0'
        }):
            result = self.client.normalize_quantity('TEST_USDT', 1.0)
            self.assertEqual(result, '1.0')
            self.assertIsInstance(result, str)
    
    def test_failsafe_when_instrument_not_found(self):
        """Test fail-safe behavior when instrument metadata not available (blocks order)"""
        with patch.object(self.client, '_get_instrument_metadata', return_value=None):
            # FAIL-SAFE: Should return None to block order when rules unavailable
            result = self.client.normalize_quantity('UNKNOWN_USDT', 6.42508353)
            self.assertIsNone(result, "Should return None to block order when instrument rules unavailable")
    
    def test_no_scientific_notation(self):
        """Test that result never uses scientific notation"""
        with patch.object(self.client, '_get_instrument_metadata', return_value={
            'quantity_decimals': 8,
            'qty_tick_size': '0.00000001',
            'min_quantity': '0.00000001'
        }):
            # Very small number that might trigger scientific notation
            result = self.client.normalize_quantity('TEST_USDT', 0.00001234)
            self.assertIsInstance(result, str)
            self.assertNotIn('e', result.lower())
            self.assertNotIn('E', result)


if __name__ == '__main__':
    unittest.main()

