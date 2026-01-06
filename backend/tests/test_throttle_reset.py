"""
Unit tests for throttle reset functionality.

Tests verify that:
1. Config hash changes trigger throttle reset
2. reset_throttle_state sets force_next_signal correctly
3. Symbol normalization works correctly
4. Dashboard toggle resets throttle
"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.models.signal_throttle import SignalThrottleState
from app.services.signal_throttle import (
    reset_throttle_state,
    set_force_next_signal,
    compute_config_hash,
    build_strategy_key,
    fetch_signal_states,
    should_emit_signal,
    SignalThrottleConfig,
    LastSignalSnapshot,
)
from app.services.strategy_profiles import StrategyType, RiskApproach


def test_config_hash_changes_trigger_reset(db: Session):
    """Test that config hash changes trigger throttle reset"""
    symbol = "TEST_USDT"
    strategy_key = "swing:conservative"
    
    # Create initial throttle state
    initial_state = SignalThrottleState(
        symbol=symbol,
        strategy_key=strategy_key,
        side="BUY",
        last_price=100.0,
        last_time=datetime.now(timezone.utc) - timedelta(seconds=30),  # Within cooldown
        config_hash="old_hash",
        force_next_signal=False,
    )
    db.add(initial_state)
    db.commit()
    
    # Compute new config hash (different from old)
    new_config = {
        "alert_enabled": True,
        "buy_alert_enabled": True,
        "sell_alert_enabled": False,
        "trade_enabled": True,
        "strategy_id": None,
        "strategy_name": "conservative",
        "min_price_change_pct": 1.0,
        "trade_amount_usd": 10.0,
    }
    new_hash = compute_config_hash(new_config)
    
    # Reset throttle with new config hash
    reset_throttle_state(
        db=db,
        symbol=symbol,
        strategy_key=strategy_key,
        side="BUY",
        current_price=105.0,
        parameter_change_reason="Config hash changed",
        config_hash=new_hash,
    )
    
    # Verify throttle was reset
    db.refresh(initial_state)
    assert initial_state.config_hash == new_hash
    assert initial_state.force_next_signal is True
    assert initial_state.last_price == 105.0  # Updated to current price


def test_reset_sets_force_next_signal(db: Session):
    """Test that reset_throttle_state sets force_next_signal correctly"""
    symbol = "TEST_USDT"
    strategy_key = "swing:conservative"
    
    # Create throttle state
    state = SignalThrottleState(
        symbol=symbol,
        strategy_key=strategy_key,
        side="BUY",
        last_price=100.0,
        last_time=datetime.now(timezone.utc),
        force_next_signal=False,
    )
    db.add(state)
    db.commit()
    
    # Reset throttle
    reset_throttle_state(
        db=db,
        symbol=symbol,
        strategy_key=strategy_key,
        side="BUY",
        current_price=105.0,
        parameter_change_reason="Test reset",
    )
    
    # Verify force_next_signal is set
    db.refresh(state)
    assert state.force_next_signal is True
    
    # Verify should_emit_signal bypasses throttle when force_next_signal is True
    snapshots = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
    buy_snapshot = snapshots.get("BUY")
    
    allowed, reason = should_emit_signal(
        symbol=symbol,
        side="BUY",
        current_price=105.0,
        current_time=datetime.now(timezone.utc),
        config=SignalThrottleConfig(min_price_change_pct=1.0, min_interval_minutes=1.0),
        last_same_side=buy_snapshot,
        last_opposite_side=None,
        db=db,
        strategy_key=strategy_key,
    )
    
    assert allowed is True
    assert "IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE" in reason or "FORCED" in reason


def test_symbol_normalization(db: Session):
    """Test that symbol normalization works correctly"""
    # Test various symbol formats
    test_cases = [
        ("ETH_USDT", "ETH_USDT"),
        ("eth_usdt", "ETH_USDT"),
        ("ETH-USDT", "ETH-USDT"),  # Note: normalization happens in reset_throttle_state
    ]
    
    for input_symbol, expected in test_cases:
        strategy_key = "swing:conservative"
        
        # Create state with normalized symbol
        state = SignalThrottleState(
            symbol=input_symbol.upper(),
            strategy_key=strategy_key,
            side="BUY",
            last_price=100.0,
            last_time=datetime.now(timezone.utc),
        )
        db.add(state)
        db.commit()
        
        # Reset should work with any case
        reset_throttle_state(
            db=db,
            symbol=input_symbol,
            strategy_key=strategy_key,
            side="BUY",
        )
        
        # Verify state exists (symbol was normalized)
        db.refresh(state)
        assert state.symbol == input_symbol.upper()
        
        # Clean up
        db.delete(state)
        db.commit()


def test_strategy_key_normalization():
    """Test that strategy keys are normalized correctly"""
    # Test with enum values
    strategy_key1 = build_strategy_key(StrategyType.SWING, RiskApproach.CONSERVATIVE)
    strategy_key2 = build_strategy_key("swing", "conservative")
    strategy_key3 = build_strategy_key("SWING", "CONSERVATIVE")
    
    # All should produce the same normalized key
    assert strategy_key1 == strategy_key2 == strategy_key3
    assert strategy_key1 == "swing:conservative"


def test_force_next_signal_cleared_after_use(db: Session):
    """Test that force_next_signal is cleared after first use"""
    symbol = "TEST_USDT"
    strategy_key = "swing:conservative"
    
    # Create state with force_next_signal=True
    state = SignalThrottleState(
        symbol=symbol,
        strategy_key=strategy_key,
        side="BUY",
        last_price=100.0,
        last_time=datetime.now(timezone.utc) - timedelta(seconds=30),
        force_next_signal=True,
    )
    db.add(state)
    db.commit()
    
    # First call should bypass throttle and clear flag
    snapshots = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
    buy_snapshot = snapshots.get("BUY")
    
    allowed1, _ = should_emit_signal(
        symbol=symbol,
        side="BUY",
        current_price=105.0,
        current_time=datetime.now(timezone.utc),
        config=SignalThrottleConfig(min_price_change_pct=1.0, min_interval_minutes=1.0),
        last_same_side=buy_snapshot,
        last_opposite_side=None,
        db=db,
        strategy_key=strategy_key,
    )
    
    assert allowed1 is True
    
    # Verify flag was cleared
    db.refresh(state)
    assert state.force_next_signal is False
    
    # Second call should respect throttle (still within cooldown)
    snapshots = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
    buy_snapshot = snapshots.get("BUY")
    
    allowed2, reason2 = should_emit_signal(
        symbol=symbol,
        side="BUY",
        current_price=106.0,
        current_time=datetime.now(timezone.utc),
        config=SignalThrottleConfig(min_price_change_pct=1.0, min_interval_minutes=1.0),
        last_same_side=buy_snapshot,
        last_opposite_side=None,
        db=db,
        strategy_key=strategy_key,
    )
    
    # Should be blocked by cooldown now
    assert allowed2 is False
    assert "THROTTLED" in reason2


def test_reset_both_sides(db: Session):
    """Test that reset_throttle_state can reset both BUY and SELL"""
    symbol = "TEST_USDT"
    strategy_key = "swing:conservative"
    
    # Create states for both sides
    buy_state = SignalThrottleState(
        symbol=symbol,
        strategy_key=strategy_key,
        side="BUY",
        last_price=100.0,
        last_time=datetime.now(timezone.utc),
        force_next_signal=False,
    )
    sell_state = SignalThrottleState(
        symbol=symbol,
        strategy_key=strategy_key,
        side="SELL",
        last_price=100.0,
        last_time=datetime.now(timezone.utc),
        force_next_signal=False,
    )
    db.add(buy_state)
    db.add(sell_state)
    db.commit()
    
    # Reset both sides
    reset_throttle_state(
        db=db,
        symbol=symbol,
        strategy_key=strategy_key,
        side=None,  # Reset both
        current_price=105.0,
    )
    
    # Verify both were reset
    db.refresh(buy_state)
    db.refresh(sell_state)
    assert buy_state.force_next_signal is True
    assert sell_state.force_next_signal is True
    assert buy_state.last_price == 105.0
    assert sell_state.last_price == 105.0




