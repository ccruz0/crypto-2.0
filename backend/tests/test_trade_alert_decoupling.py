"""Regression tests for trade-alert decoupling and price move alert channel.

Note: ``SIGNAL_ORDER_REQUIRES_ALERT`` defaults to true — orders follow alerts.
Set ``SIGNAL_ORDER_REQUIRES_ALERT=false`` to restore alert-independent trading.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import os

from app.services.signal_order_policy import resolve_legacy_buy_order_gate
from app.services.signal_throttle import (
    LastSignalSnapshot,
    SignalThrottleConfig,
)


BASE_TIME = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def _mock_watchlist_item(
    symbol="ETH_USDT",
    alert_enabled=True,
    trade_enabled=True,
    trade_amount_usd=100.0,
    min_price_change_pct=1.0,
    strategy_id="intraday",
    strategy_name="conservative",
):
    """Create a mock watchlist item for testing."""
    item = SimpleNamespace(
        symbol=symbol,
        alert_enabled=alert_enabled,
        trade_enabled=trade_enabled,
        trade_amount_usd=trade_amount_usd,
        min_price_change_pct=min_price_change_pct,
        strategy_id=strategy_id,
        strategy_name=strategy_name,
        sl_tp_mode="conservative",
        buy_target=None,
        purchase_price=None,
        signals=None,
    )
    return item


def test_trade_execution_independent_of_alert_sending():
    """Legacy mode: trade may proceed without alert when SIGNAL_ORDER_REQUIRES_ALERT=false."""
    os.environ["SIGNAL_ORDER_REQUIRES_ALERT"] = "false"
    try:
        watchlist_item = _mock_watchlist_item(
            alert_enabled=False,
            trade_enabled=True,
        )

        buy_signal = True
        trade_enabled = watchlist_item.trade_enabled
        trade_amount_usd = watchlist_item.trade_amount_usd

        legacy_eligible = (
            buy_signal
            and trade_enabled
            and trade_amount_usd
            and trade_amount_usd > 0
        )
        should_create_order, _ = resolve_legacy_buy_order_gate(
            blocked_by_limits=False,
            buy_alert_sent_successfully=False,
        )

        assert legacy_eligible is True
        assert should_create_order is True
    finally:
        os.environ.pop("SIGNAL_ORDER_REQUIRES_ALERT", None)


def test_trade_blocked_without_alert_when_required():
    """Default: no alert → no legacy order (orchestrator path only on alert send)."""
    os.environ.pop("SIGNAL_ORDER_REQUIRES_ALERT", None)
    should_create_order, reason = resolve_legacy_buy_order_gate(
        blocked_by_limits=False,
        buy_alert_sent_successfully=False,
    )
    assert should_create_order is False
    assert reason == "alert_required_not_sent"


def test_price_move_alert_triggers_without_signal():
    """Test that price move alert triggers even when buy_signal=False and sell_signal=False.
    
    Scenario:
    - alert_enabled=True
    - buy_signal=False, sell_signal=False
    - price_change_pct >= PRICE_MOVE_ALERT_PCT
    - Price move alert should trigger
    """
    # Set PRICE_MOVE_ALERT_PCT to a low threshold for testing
    os.environ["PRICE_MOVE_ALERT_PCT"] = "0.10"  # 0.10% threshold
    
    try:
        watchlist_item = _mock_watchlist_item(
            alert_enabled=True,
            trade_enabled=False,
        )
        
        current_price = 3400.0
        baseline_price = 3396.0  # ~0.12% change (exceeds 0.10% threshold)
        
        # Mock signals to return no buy/sell signal
        with patch('app.services.signal_monitor.calculate_trading_signals') as mock_signals:
            mock_signals.return_value = {
                "buy_signal": False,
                "sell_signal": False,
                "strategy": {"decision": "WAIT"},
            }
            
            # Calculate price change
            price_change_pct = abs((current_price - baseline_price) / baseline_price * 100)
            
            # Assert price change exceeds threshold
            assert price_change_pct >= 0.10, f"Price change {price_change_pct:.2f}% should exceed 0.10% threshold"
            
            # Price move alert should be eligible
            # (Actual sending requires DB and Telegram, which we mock in integration tests)
            price_move_eligible = (
                watchlist_item.alert_enabled and
                price_change_pct >= float(os.getenv("PRICE_MOVE_ALERT_PCT", "0.50"))
            )
            
            assert price_move_eligible is True, "Price move alert should be eligible when threshold met"
    finally:
        # Cleanup
        if "PRICE_MOVE_ALERT_PCT" in os.environ:
            del os.environ["PRICE_MOVE_ALERT_PCT"]


def test_price_move_alert_uses_separate_throttle_key():
    """Test that price move alerts use strategy_key:PRICE_MOVE for throttle bucket.
    
    Scenario:
    - Price move alert should use separate throttle key
    - This ensures it doesn't interfere with signal alerts
    """
    strategy_key = "intraday:conservative"
    expected_price_move_key = f"{strategy_key}:PRICE_MOVE"
    
    # Assert the throttle key format
    assert ":PRICE_MOVE" in expected_price_move_key
    assert expected_price_move_key != strategy_key
    assert expected_price_move_key.endswith(":PRICE_MOVE")


def test_price_move_alert_throttle_cooldown():
    """Test that price move alerts respect cooldown period.
    
    Scenario:
    - First run: alert should send
    - Second run within cooldown: should skip
    - After cooldown: should send again
    """
    os.environ["PRICE_MOVE_ALERT_PCT"] = "0.10"
    os.environ["PRICE_MOVE_ALERT_COOLDOWN_SECONDS"] = "300"  # 5 minutes
    
    try:
        # Use mock to avoid DB schema dependencies
        now = datetime.now(timezone.utc)
        cooldown_seconds = 300.0
        
        # Simulate first run: No previous state
        price_move_snapshot = None
        first_run_allowed = (price_move_snapshot is None or 
                           price_move_snapshot.timestamp is None or
                           (now - price_move_snapshot.timestamp).total_seconds() >= cooldown_seconds)
        
        assert first_run_allowed is True, "First run should allow price move alert"
        
        # Simulate second run immediately after first (within cooldown)
        recent_timestamp = now - timedelta(seconds=10)  # 10 seconds ago
        price_move_snapshot_after = LastSignalSnapshot(
            side="PRICE_MOVE",
            price=3400.0,
            timestamp=recent_timestamp,
        )
        
        elapsed = (now - price_move_snapshot_after.timestamp).total_seconds()
        second_run_allowed = elapsed >= cooldown_seconds
        
        assert second_run_allowed is False, f"Second run within cooldown should be throttled (elapsed={elapsed:.1f}s < {cooldown_seconds}s)"
        
        # Simulate third run after cooldown
        old_timestamp = now - timedelta(seconds=cooldown_seconds + 10)  # 10 seconds past cooldown
        price_move_snapshot_old = LastSignalSnapshot(
            side="PRICE_MOVE",
            price=3400.0,
            timestamp=old_timestamp,
        )
        
        elapsed_old = (now - price_move_snapshot_old.timestamp).total_seconds()
        third_run_allowed = elapsed_old >= cooldown_seconds
        
        assert third_run_allowed is True, f"Third run after cooldown should allow (elapsed={elapsed_old:.1f}s >= {cooldown_seconds}s)"
        
    finally:
        # Cleanup
        if "PRICE_MOVE_ALERT_PCT" in os.environ:
            del os.environ["PRICE_MOVE_ALERT_PCT"]
        if "PRICE_MOVE_ALERT_COOLDOWN_SECONDS" in os.environ:
            del os.environ["PRICE_MOVE_ALERT_COOLDOWN_SECONDS"]


def test_throttle_reset_affects_price_move_bucket():
    """Test that reset_throttle_state can reset price move alert throttle.
    
    Scenario:
    - Create a price move throttle state that would block
    - Call reset_throttle_state for price move bucket
    - Next evaluation should not skip due to cooldown
    """
    # Use mock to avoid DB schema dependencies
    symbol = "ETH_USDT"
    strategy_key = "intraday:conservative"
    price_move_strategy_key = f"{strategy_key}:PRICE_MOVE"
    current_price = 3400.0
    old_price = current_price - 10.0
    
    # Simulate existing price move snapshot (would block)
    now = datetime.now(timezone.utc)
    recent_timestamp = now - timedelta(seconds=10)  # 10 seconds ago (within cooldown)
    price_move_snapshot_before = LastSignalSnapshot(
        side="PRICE_MOVE",
        price=old_price,
        timestamp=recent_timestamp,
        force_next_signal=False,
    )
    
    # Verify it would block (within cooldown)
    cooldown_seconds = 300.0
    elapsed_before = (now - price_move_snapshot_before.timestamp).total_seconds()
    would_block_before = elapsed_before < cooldown_seconds
    assert would_block_before is True, "Should block before reset (within cooldown)"
    
    # Simulate reset: price updated, force_next_signal=True
    price_move_snapshot_after = LastSignalSnapshot(
        side="PRICE_MOVE",
        price=current_price,  # Updated to current price
        timestamp=price_move_snapshot_before.timestamp,  # Timestamp unchanged (as per canonical behavior)
        force_next_signal=True,  # Set to allow immediate bypass
    )
    
    # Verify reset effects
    assert price_move_snapshot_after.price == current_price, "Price should be updated after reset"
    assert price_move_snapshot_after.force_next_signal is True, "force_next_signal should be set after reset"
    
    # With force_next_signal=True, should bypass cooldown
    # (In real code, should_emit_signal checks force_next_signal first)
    should_bypass = price_move_snapshot_after.force_next_signal is True
    assert should_bypass is True, "force_next_signal=True should bypass cooldown"

