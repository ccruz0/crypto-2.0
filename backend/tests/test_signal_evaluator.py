"""
Tests for the canonical signal evaluator.

These tests verify that evaluate_signal_for_symbol() produces consistent results
that match what the debug script and live monitor expect.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from app.services.signal_evaluator import evaluate_signal_for_symbol
from app.models.watchlist import WatchlistItem


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = MagicMock()
    db.expire_all = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


@pytest.fixture
def watchlist_item():
    """Watchlist item for testing"""
    item = MagicMock(spec=WatchlistItem)
    item.symbol = "TEST_USDT"
    item.exchange = "CRYPTO_COM"
    item.alert_enabled = True
    item.buy_alert_enabled = True
    item.sell_alert_enabled = True
    item.trade_enabled = False
    item.trade_amount_usd = 100.0
    item.sl_tp_mode = "conservative"
    item.buy_target = None
    item.purchase_price = None
    item.min_price_change_pct = None
    item.alert_cooldown_minutes = None
    return item


@patch("app.services.signal_evaluator.get_price_with_fallback")
@patch("app.services.signal_evaluator.calculate_trading_signals")
@patch("app.services.signal_evaluator.should_emit_signal")
@patch("app.services.signal_evaluator.fetch_signal_states")
@patch("app.services.signal_evaluator.resolve_strategy_profile")
@patch("app.services.signal_evaluator.get_strategy_rules")
def test_evaluate_signal_sell_signal_allowed(
    mock_get_strategy_rules,
    mock_resolve_strategy_profile,
    mock_fetch_signal_states,
    mock_should_emit_signal,
    mock_calculate_trading_signals,
    mock_get_price_with_fallback,
    mock_db,
    watchlist_item,
):
    """Test that a SELL signal with sufficient volume produces can_emit_sell_alert=True"""
    # Setup mocks
    from app.services.strategy_profiles import StrategyType, RiskApproach
    
    mock_resolve_strategy_profile.return_value = (StrategyType.SWING, RiskApproach.CONSERVATIVE)
    mock_get_strategy_rules.return_value = {"volumeMinRatio": 0.5}
    
    # Mock MarketPrice and MarketData
    mock_mp = MagicMock()
    mock_mp.price = 100.0
    mock_mp.volume_24h = 100000.0
    
    mock_md = MagicMock()
    mock_md.rsi = 75.0
    mock_md.ma50 = 95.0
    mock_md.ma200 = 90.0
    mock_md.ema10 = 98.0
    mock_md.atr = 2.0
    mock_md.ma10w = 90.0
    mock_md.current_volume = 5000.0
    mock_md.avg_volume = 2000.0
    
    mock_db.query.return_value.filter.side_effect = [
        MagicMock(first=lambda: mock_mp),  # MarketPrice
        MagicMock(first=lambda: mock_md),   # MarketData
    ]
    
    # Mock calculate_trading_signals to return SELL signal
    mock_calculate_trading_signals.return_value = {
        "buy_signal": False,
        "sell_signal": True,
        "strategy_state": {
            "decision": "SELL",
            "index": 75,
            "reasons": {
                "sell_rsi_ok": True,
                "sell_trend_ok": True,
                "sell_volume_ok": True,
            }
        }
    }
    
    # Mock throttle to allow emission
    mock_should_emit_signal.return_value = (True, "Allowed")
    mock_fetch_signal_states.return_value = {}
    
    # Run evaluation
    result = evaluate_signal_for_symbol(mock_db, watchlist_item, "TEST_USDT")
    
    # Assertions
    assert result["decision"] == "SELL"
    assert result["sell_signal"] is True
    assert result["buy_signal"] is False
    assert result["sell_allowed"] is True
    assert result["sell_flag_allowed"] is True
    assert result["can_emit_sell_alert"] is True
    assert result["throttle_status_sell"] == "SENT"
    assert result["index"] == 75


@patch("app.services.signal_evaluator.get_price_with_fallback")
@patch("app.services.signal_evaluator.calculate_trading_signals")
@patch("app.services.signal_evaluator.should_emit_signal")
@patch("app.services.signal_evaluator.fetch_signal_states")
@patch("app.services.signal_evaluator.resolve_strategy_profile")
@patch("app.services.signal_evaluator.get_strategy_rules")
def test_evaluate_signal_volume_below_threshold(
    mock_get_strategy_rules,
    mock_resolve_strategy_profile,
    mock_fetch_signal_states,
    mock_should_emit_signal,
    mock_calculate_trading_signals,
    mock_get_price_with_fallback,
    mock_db,
    watchlist_item,
):
    """Test that low volume produces decision=WAIT even if RSI and trend are OK"""
    from app.services.strategy_profiles import StrategyType, RiskApproach
    
    mock_resolve_strategy_profile.return_value = (StrategyType.SWING, RiskApproach.CONSERVATIVE)
    mock_get_strategy_rules.return_value = {"volumeMinRatio": 0.5}
    
    # Mock MarketPrice and MarketData with low volume
    mock_mp = MagicMock()
    mock_mp.price = 100.0
    mock_mp.volume_24h = 10000.0
    
    mock_md = MagicMock()
    mock_md.rsi = 75.0  # High RSI (SELL condition)
    mock_md.ma50 = 95.0
    mock_md.ma200 = 90.0
    mock_md.ema10 = 98.0
    mock_md.atr = 2.0
    mock_md.ma10w = 90.0
    mock_md.current_volume = 100.0  # Low volume
    mock_md.avg_volume = 1000.0    # Average volume
    
    mock_db.query.return_value.filter.side_effect = [
        MagicMock(first=lambda: mock_mp),
        MagicMock(first=lambda: mock_md),
    ]
    
    # Mock calculate_trading_signals to return no signal (volume too low)
    mock_calculate_trading_signals.return_value = {
        "buy_signal": False,
        "sell_signal": False,  # Volume check fails
        "strategy_state": {
            "decision": "WAIT",
            "index": 0,
            "reasons": {
                "sell_rsi_ok": True,
                "sell_trend_ok": True,
                "sell_volume_ok": False,  # Volume below threshold
            }
        }
    }
    
    # Run evaluation
    result = evaluate_signal_for_symbol(mock_db, watchlist_item, "TEST_USDT")
    
    # Assertions
    assert result["decision"] == "WAIT"
    assert result["sell_signal"] is False
    assert result["buy_signal"] is False
    assert result["can_emit_sell_alert"] is False
    assert result["throttle_status_sell"] == "N/A"
    assert "volume" in result["missing_indicators"] or result["volume_ratio"] is None or result["volume_ratio"] < 0.5

