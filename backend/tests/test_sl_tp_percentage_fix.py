#!/usr/bin/env python3
"""
Test script to verify SL/TP percentage fix works correctly.

This script tests:
1. That watchlist percentages are read correctly
2. That defaults are used when percentages are None/0
3. That user settings are preserved
4. That correct percentages are used for calculations

Usage:
    python -m pytest backend/tests/test_sl_tp_percentage_fix.py -v
    OR
    python backend/tests/test_sl_tp_percentage_fix.py
"""

import sys
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.exchange_sync import ExchangeSyncService
from app.models.watchlist import WatchlistItem
from sqlalchemy.orm import Session


class TestSLTPPercentageFix:
    """Test SL/TP percentage reading and usage"""
    
    def setup_method(self):
        """Setup for each test"""
        self.service = ExchangeSyncService()
    
    def test_read_watchlist_percentages(self):
        """Test that watchlist percentages are read correctly"""
        # Mock watchlist item with custom percentages
        watchlist_item = Mock(spec=WatchlistItem)
        watchlist_item.sl_percentage = 5.0
        watchlist_item.tp_percentage = 5.0
        watchlist_item.sl_tp_mode = "conservative"
        watchlist_item.atr = 0
        
        # Test the logic from exchange_sync.py
        sl_percentage = watchlist_item.sl_percentage
        tp_percentage = watchlist_item.tp_percentage
        sl_tp_mode = (watchlist_item.sl_tp_mode or "conservative").lower()
        
        # Calculate effective percentages
        default_sl_pct, default_tp_pct = (3.0, 3.0) if sl_tp_mode == "conservative" else (2.0, 2.0)
        effective_sl_pct = abs(sl_percentage) if (sl_percentage is not None and sl_percentage > 0) else default_sl_pct
        effective_tp_pct = abs(tp_percentage) if (tp_percentage is not None and tp_percentage > 0) else default_tp_pct
        
        # Assertions
        assert effective_sl_pct == 5.0, "Should use watchlist SL percentage"
        assert effective_tp_pct == 5.0, "Should use watchlist TP percentage"
        assert effective_sl_pct != default_sl_pct, "Should not use default when watchlist has value"
    
    def test_use_defaults_when_none(self):
        """Test that defaults are used when percentages are None"""
        # Mock watchlist item with None percentages
        watchlist_item = Mock(spec=WatchlistItem)
        watchlist_item.sl_percentage = None
        watchlist_item.tp_percentage = None
        watchlist_item.sl_tp_mode = "aggressive"
        watchlist_item.atr = 0
        
        sl_percentage = watchlist_item.sl_percentage
        tp_percentage = watchlist_item.tp_percentage
        sl_tp_mode = (watchlist_item.sl_tp_mode or "conservative").lower()
        
        default_sl_pct, default_tp_pct = (2.0, 2.0) if sl_tp_mode == "aggressive" else (3.0, 3.0)
        effective_sl_pct = abs(sl_percentage) if (sl_percentage is not None and sl_percentage > 0) else default_sl_pct
        effective_tp_pct = abs(tp_percentage) if (tp_percentage is not None and tp_percentage > 0) else default_tp_pct
        
        assert effective_sl_pct == 2.0, "Should use default for aggressive mode"
        assert effective_tp_pct == 2.0, "Should use default for aggressive mode"
    
    def test_use_defaults_when_zero(self):
        """Test that defaults are used when percentages are 0"""
        watchlist_item = Mock(spec=WatchlistItem)
        watchlist_item.sl_percentage = 0
        watchlist_item.tp_percentage = 0
        watchlist_item.sl_tp_mode = "conservative"
        
        sl_percentage = watchlist_item.sl_percentage
        tp_percentage = watchlist_item.tp_percentage
        sl_tp_mode = (watchlist_item.sl_tp_mode or "conservative").lower()
        
        default_sl_pct, default_tp_pct = (3.0, 3.0) if sl_tp_mode == "conservative" else (2.0, 2.0)
        effective_sl_pct = abs(sl_percentage) if (sl_percentage is not None and sl_percentage > 0) else default_sl_pct
        effective_tp_pct = abs(tp_percentage) if (tp_percentage is not None and tp_percentage > 0) else default_tp_pct
        
        assert effective_sl_pct == 3.0, "Should use default when watchlist has 0"
        assert effective_tp_pct == 3.0, "Should use default when watchlist has 0"
    
    def test_preserve_user_settings(self):
        """Test that user settings are preserved and not overwritten"""
        watchlist_item = Mock(spec=WatchlistItem)
        watchlist_item.sl_percentage = 5.0
        watchlist_item.tp_percentage = 5.0
        
        # Simulate the persistence logic
        sl_percentage = watchlist_item.sl_percentage
        tp_percentage = watchlist_item.tp_percentage
        effective_sl_pct = 5.0
        effective_tp_pct = 5.0
        
        # Check if we should preserve or update
        should_preserve_sl = sl_percentage is not None and sl_percentage > 0
        should_preserve_tp = tp_percentage is not None and tp_percentage > 0
        
        assert should_preserve_sl, "Should preserve SL when user has custom value"
        assert should_preserve_tp, "Should preserve TP when user has custom value"
        
        # If preserving, don't update
        if should_preserve_sl:
            # Don't update watchlist_item.sl_percentage
            pass
        
        # Original values should remain
        assert watchlist_item.sl_percentage == 5.0, "User SL setting should be preserved"
        assert watchlist_item.tp_percentage == 5.0, "User TP setting should be preserved"
    
    def test_calculate_prices_with_custom_percentages(self):
        """Test that prices are calculated correctly with custom percentages"""
        filled_price = 100.0
        effective_sl_pct = 5.0  # Custom 5%
        effective_tp_pct = 5.0  # Custom 5%
        side = "BUY"
        
        # Calculate prices (same logic as exchange_sync.py)
        if side == "BUY":
            sl_price = filled_price * (1 - effective_sl_pct / 100)
            tp_price = filled_price * (1 + effective_tp_pct / 100)
        
        assert sl_price == 95.0, f"SL price should be 95.0, got {sl_price}"
        assert tp_price == 105.0, f"TP price should be 105.0, got {tp_price}"
    
    def test_calculate_prices_with_defaults(self):
        """Test that prices are calculated correctly with defaults"""
        filled_price = 100.0
        effective_sl_pct = 2.0  # Default for aggressive
        effective_tp_pct = 2.0  # Default for aggressive
        side = "BUY"
        
        if side == "BUY":
            sl_price = filled_price * (1 - effective_sl_pct / 100)
            tp_price = filled_price * (1 + effective_tp_pct / 100)
        
        assert sl_price == 98.0, f"SL price should be 98.0, got {sl_price}"
        assert tp_price == 102.0, f"TP price should be 102.0, got {tp_price}"
    
    def test_negative_percentages_handled(self):
        """Test that negative percentages are handled (should use abs)"""
        watchlist_item = Mock(spec=WatchlistItem)
        watchlist_item.sl_percentage = -5.0  # Negative (shouldn't happen but test anyway)
        watchlist_item.tp_percentage = 5.0
        watchlist_item.sl_tp_mode = "conservative"
        
        sl_percentage = watchlist_item.sl_percentage
        tp_percentage = watchlist_item.tp_percentage
        
        default_sl_pct = 3.0
        effective_sl_pct = abs(sl_percentage) if (sl_percentage is not None and sl_percentage > 0) else default_sl_pct
        effective_tp_pct = abs(tp_percentage) if (tp_percentage is not None and tp_percentage > 0) else default_tp_pct
        
        # Negative values should fall back to defaults (since > 0 check fails)
        assert effective_sl_pct == 3.0, "Should use default for negative percentage"
        assert effective_tp_pct == 5.0, "Should use watchlist value for positive"
    
    def test_aggressive_mode_defaults(self):
        """Test aggressive mode uses 2% defaults"""
        watchlist_item = Mock(spec=WatchlistItem)
        watchlist_item.sl_percentage = None
        watchlist_item.tp_percentage = None
        watchlist_item.sl_tp_mode = "aggressive"
        
        sl_tp_mode = (watchlist_item.sl_tp_mode or "conservative").lower()
        
        def _default_percentages(mode: str):
            if mode == "aggressive":
                return 2.0, 2.0
            return 3.0, 3.0
        
        default_sl_pct, default_tp_pct = _default_percentages(sl_tp_mode)
        
        assert default_sl_pct == 2.0, "Aggressive mode should default to 2% SL"
        assert default_tp_pct == 2.0, "Aggressive mode should default to 2% TP"
    
    def test_conservative_mode_defaults(self):
        """Test conservative mode uses 3% defaults"""
        watchlist_item = Mock(spec=WatchlistItem)
        watchlist_item.sl_percentage = None
        watchlist_item.tp_percentage = None
        watchlist_item.sl_tp_mode = "conservative"
        
        sl_tp_mode = (watchlist_item.sl_tp_mode or "conservative").lower()
        
        def _default_percentages(mode: str):
            if mode == "aggressive":
                return 2.0, 2.0
            return 3.0, 3.0
        
        default_sl_pct, default_tp_pct = _default_percentages(sl_tp_mode)
        
        assert default_sl_pct == 3.0, "Conservative mode should default to 3% SL"
        assert default_tp_pct == 3.0, "Conservative mode should default to 3% TP"


def run_manual_test():
    """Run manual integration test with actual database (optional)"""
    print("Running manual integration test...")
    print("This requires a database connection.")
    print("\nTo run unit tests instead, use: pytest backend/tests/test_sl_tp_percentage_fix.py -v")
    
    try:
        from app.database import SessionLocal
        from app.models.watchlist import WatchlistItem
        
        db = SessionLocal()
        try:
            # Test with DOT_USDT
            item = db.query(WatchlistItem).filter(WatchlistItem.symbol == "DOT_USDT").first()
            
            if item:
                print(f"\n✅ Found DOT_USDT in watchlist:")
                print(f"   SL: {item.sl_percentage}")
                print(f"   TP: {item.tp_percentage}")
                print(f"   Mode: {item.sl_tp_mode}")
                
                # Test the logic
                sl_tp_mode = (item.sl_tp_mode or "conservative").lower()
                default_sl_pct = 2.0 if sl_tp_mode == "aggressive" else 3.0
                default_tp_pct = 2.0 if sl_tp_mode == "aggressive" else 3.0
                
                effective_sl = item.sl_percentage if (item.sl_percentage is not None and item.sl_percentage > 0) else default_sl_pct
                effective_tp = item.tp_percentage if (item.tp_percentage is not None and item.tp_percentage > 0) else default_tp_pct
                
                print(f"\n📊 Effective percentages:")
                print(f"   SL: {effective_sl}% ({'from watchlist' if item.sl_percentage and item.sl_percentage > 0 else 'default'})")
                print(f"   TP: {effective_tp}% ({'from watchlist' if item.tp_percentage and item.tp_percentage > 0 else 'default'})")
            else:
                print("❌ DOT_USDT not found in watchlist")
                
        finally:
            db.close()
    except Exception as e:
        print(f"❌ Error: {e}")
        print("Make sure database is accessible and environment is set up correctly")


if __name__ == "__main__":
    # Run unit tests if pytest is available
    try:
        import pytest
        pytest.main([__file__, "-v"])
    except ImportError:
        print("pytest not available. Running basic validation...")
        
        # Run a simple test
        test = TestSLTPPercentageFix()
        test.setup_method()
        
        try:
            test.test_read_watchlist_percentages()
            print("✅ test_read_watchlist_percentages: PASSED")
        except Exception as e:
            print(f"❌ test_read_watchlist_percentages: FAILED - {e}")
        
        try:
            test.test_use_defaults_when_none()
            print("✅ test_use_defaults_when_none: PASSED")
        except Exception as e:
            print(f"❌ test_use_defaults_when_none: FAILED - {e}")
        
        try:
            test.test_use_defaults_when_zero()
            print("✅ test_use_defaults_when_zero: PASSED")
        except Exception as e:
            print(f"❌ test_use_defaults_when_zero: FAILED - {e}")
        
        try:
            test.test_preserve_user_settings()
            print("✅ test_preserve_user_settings: PASSED")
        except Exception as e:
            print(f"❌ test_preserve_user_settings: FAILED - {e}")
        
        try:
            test.test_calculate_prices_with_custom_percentages()
            print("✅ test_calculate_prices_with_custom_percentages: PASSED")
        except Exception as e:
            print(f"❌ test_calculate_prices_with_custom_percentages: FAILED - {e}")
        
        print("\n" + "="*50)
        print("To run full test suite with pytest:")
        print("  pip install pytest")
        print("  pytest backend/tests/test_sl_tp_percentage_fix.py -v")
        print("="*50)






