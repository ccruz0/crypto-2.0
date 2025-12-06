"""
Tests for EMA10 blocking logic when not configured.

These tests verify that:
1. EMA10 does NOT block signals when check_ema10=False
2. EMA10 DOES block signals when check_ema10=True and ema10 is None (and no MA50 fallback)
3. EMA10 is evaluated normally when check_ema10=True and ema10 is available
"""

import pytest
from unittest.mock import patch
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import StrategyType, RiskApproach


def test_ema10_disabled_does_not_block():
    """Test that EMA10 does NOT block when check_ema10=False, even if ema10 is None."""
    # Mock get_strategy_rules to return config with EMA10 disabled
    with patch('app.services.trading_signals.get_strategy_rules') as mock_get_rules:
        mock_get_rules.return_value = {
            "rsi": {"buyBelow": 55, "sellAbove": 65},
            "maChecks": {
                "ema10": False,  # EMA10 is NOT enabled
                "ma50": False,
                "ma200": False,
            },
            "volumeMinRatio": 0.5,
        }
        
        # Call with RSI < threshold, volume OK, but ema10=None
        result = calculate_trading_signals(
            symbol="TEST_USDT",
            price=100.0,
            rsi=30.0,  # Below threshold (55 for scalp-aggressive)
            volume=1000.0,
            avg_volume=500.0,  # Volume ratio = 2.0 (above 0.5 threshold)
            ma50=None,
            ma200=None,
            ema10=None,  # EMA10 data is missing
            strategy_type=StrategyType.SCALP,
            risk_approach=RiskApproach.AGGRESSIVE,
        )
        
        # Should NOT be blocked by EMA10 since check_ema10=False
        strategy = result.get("strategy", {})
        decision = strategy.get("decision")
        reasons = strategy.get("reasons", {})
        
        assert decision == "BUY" or result.get("buy_signal") is True, \
            f"Signal should NOT be blocked when EMA10 is disabled. Decision: {decision}, Reasons: {reasons}"
        assert reasons.get("buy_ma_ok") is not False, \
            "buy_ma_ok should not be False when EMA10 is disabled (no MAs required)"


def test_ema10_enabled_but_missing_blocks():
    """Test that EMA10 DOES block when check_ema10=True and ema10 is None (no MA50 fallback)."""
    # Mock get_strategy_rules to return config with EMA10 enabled
    with patch('app.services.trading_signals.get_strategy_rules') as mock_get_rules:
        mock_get_rules.return_value = {
            "rsi": {"buyBelow": 55, "sellAbove": 65},
            "maChecks": {
                "ema10": True,  # EMA10 IS enabled
                "ma50": False,  # No fallback
                "ma200": False,
            },
            "volumeMinRatio": 0.5,
        }
        
        # Call with RSI < threshold, volume OK, but ema10=None
        result = calculate_trading_signals(
            symbol="TEST_USDT",
            price=100.0,
            rsi=30.0,
            volume=1000.0,
            avg_volume=500.0,
            ma50=None,
            ma200=None,
            ema10=None,  # EMA10 data is missing
            strategy_type=StrategyType.SCALP,
            risk_approach=RiskApproach.AGGRESSIVE,
        )
        
        # SHOULD be blocked by EMA10 since check_ema10=True and ema10 is None
        strategy = result.get("strategy", {})
        decision = strategy.get("decision")
        reasons = strategy.get("reasons", {})
        
        assert decision != "BUY" or result.get("buy_signal") is False, \
            f"Signal SHOULD be blocked when EMA10 is required but missing. Decision: {decision}, Reasons: {reasons}"
        assert reasons.get("buy_ma_ok") is False, \
            "buy_ma_ok should be False when EMA10 is required but missing"


def test_ema10_enabled_with_data_evaluates_normally():
    """Test that EMA10 is evaluated normally when check_ema10=True and ema10 data is available."""
    # Mock get_strategy_rules to return config with EMA10 enabled
    with patch('app.services.trading_signals.get_strategy_rules') as mock_get_rules:
        mock_get_rules.return_value = {
            "rsi": {"buyBelow": 55, "sellAbove": 65},
            "maChecks": {
                "ema10": True,  # EMA10 IS enabled
                "ma50": False,
                "ma200": False,
            },
            "volumeMinRatio": 0.5,
        }
        
        # Test case 1: Price > EMA10 (should pass)
        result1 = calculate_trading_signals(
            symbol="TEST_USDT",
            price=105.0,  # Price > EMA10
            rsi=30.0,
            volume=1000.0,
            avg_volume=500.0,
            ma50=None,
            ma200=None,
            ema10=100.0,  # EMA10 data is available
            strategy_type=StrategyType.SCALP,
            risk_approach=RiskApproach.AGGRESSIVE,
        )
        
        strategy1 = result1.get("strategy", {})
        decision1 = strategy1.get("decision")
        reasons1 = strategy1.get("reasons", {})
        
        assert decision1 == "BUY" or result1.get("buy_signal") is True, \
            "Should pass when price > EMA10"
        assert reasons1.get("buy_ma_ok") is True, \
            "buy_ma_ok should be True when price > EMA10"
        
        # Test case 2: Price < EMA10 but within tolerance (should pass for scalp)
        result2 = calculate_trading_signals(
            symbol="TEST_USDT",
            price=96.0,  # Price < EMA10 (4% below, within 5% tolerance for scalp)
            rsi=30.0,
            volume=1000.0,
            avg_volume=500.0,
            ma50=None,
            ma200=None,
            ema10=100.0,
            strategy_type=StrategyType.SCALP,
            risk_approach=RiskApproach.AGGRESSIVE,
        )
        
        strategy2 = result2.get("strategy", {})
        decision2 = strategy2.get("decision")
        reasons2 = strategy2.get("reasons", {})
        
        # Should pass due to 5% tolerance for scalp strategies
        assert decision2 == "BUY" or result2.get("buy_signal") is True, \
            "Should pass when price is within 5% tolerance of EMA10 (scalp)"
        assert reasons2.get("buy_ma_ok") is True, \
            "buy_ma_ok should be True when within tolerance"

