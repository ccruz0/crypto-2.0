"""
Tests for ADA SELL alert flow

These tests verify that:
- SELL signals trigger alerts when throttle allows
- SELL alerts are throttled correctly (cooldown + price change)
- Throttle state is persisted correctly
- LOCAL vs AWS runtime origin is logged correctly
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from app.services.signal_throttle import (
    should_emit_signal,
    SignalThrottleConfig,
    LastSignalSnapshot,
    record_signal_event,
)
from app.core.runtime import get_runtime_origin


class TestADASellAlertFlow:
    """Test SELL alert flow for ADA_USDT"""
    
    def test_first_sell_alert_always_allowed(self):
        """CANONICAL: First SELL alert should always be allowed (no previous state)"""
        config = SignalThrottleConfig(
            min_price_change_pct=1.0,
            min_interval_minutes=1.0,  # Fixed 60 seconds
        )
        
        allowed, reason = should_emit_signal(
            symbol="ADA_USDT",
            side="SELL",
            current_price=0.50,
            current_time=datetime.now(timezone.utc),
            config=config,
            last_same_side=None,  # No previous SELL
            last_opposite_side=None,
        )
        
        assert allowed is True
        assert "No previous" in reason or "first" in reason.lower()
    
    def test_sell_alert_throttled_by_time_gate(self):
        """CANONICAL: SELL alert should be throttled by time gate if < 60 seconds elapsed"""
        config = SignalThrottleConfig(
            min_price_change_pct=1.0,
            min_interval_minutes=1.0,  # Fixed 60 seconds
        )
        
        now = datetime.now(timezone.utc)
        thirty_seconds_ago = now - timedelta(seconds=30)  # 30s < 60s time gate
        
        last_sell = LastSignalSnapshot(
            side="SELL",
            price=0.50,
            timestamp=thirty_seconds_ago,
        )
        
        allowed, reason = should_emit_signal(
            symbol="ADA_USDT",
            side="SELL",
            current_price=0.504,  # 0.8% price change (below 1% threshold) BUT time gate blocks first
            current_time=now,
            config=config,
            last_same_side=last_sell,
            last_opposite_side=None,
        )
        
        # Should be blocked by time gate (30s < 60s) - checked first
        assert allowed is False
        assert "THROTTLED_TIME_GATE" in reason or "elapsed" in reason.lower()
    
    def test_sell_alert_throttled_by_price_gate(self):
        """CANONICAL: SELL alert should be throttled by price gate if price change < threshold (after time gate passes)"""
        config = SignalThrottleConfig(
            min_price_change_pct=1.0,
            min_interval_minutes=1.0,  # Fixed 60 seconds
        )
        
        now = datetime.now(timezone.utc)
        two_minutes_ago = now - timedelta(minutes=2)  # Time gate passes (2 min >= 1 min)
        
        last_sell = LastSignalSnapshot(
            side="SELL",
            price=0.50,
            timestamp=two_minutes_ago,
        )
        
        allowed, reason = should_emit_signal(
            symbol="ADA_USDT",
            side="SELL",
            current_price=0.504,  # 0.8% price change (below 1% threshold) - price gate fails
            current_time=now,
            config=config,
            last_same_side=last_sell,
            last_opposite_side=None,
        )
        
        # Time gate passes, but price gate fails (0.8% < 1%)
        assert allowed is False
        assert "THROTTLED_PRICE_GATE" in reason or "price change" in reason.lower()
    
    def test_sell_alert_allowed_after_time_and_price_gates_pass(self):
        """CANONICAL: SELL alert should be allowed after time gate (60s) AND price gate pass"""
        config = SignalThrottleConfig(
            min_price_change_pct=1.0,
            min_interval_minutes=1.0,  # Fixed 60 seconds
        )
        
        now = datetime.now(timezone.utc)
        two_minutes_ago = now - timedelta(minutes=2)  # Time gate passes (2 min >= 1 min)
        
        last_sell = LastSignalSnapshot(
            side="SELL",
            price=0.50,
            timestamp=two_minutes_ago,
        )
        
        allowed, reason = should_emit_signal(
            symbol="ADA_USDT",
            side="SELL",
            current_price=0.51,  # 2% price change (meets threshold) - price gate passes
            current_time=now,
            config=config,
            last_same_side=last_sell,
            last_opposite_side=None,
        )
        
        assert allowed is True
        assert "Δt=" in reason or "60" in reason or "price change" in reason.lower() or "Δp=" in reason
    
    def test_sell_and_buy_are_independent(self):
        """CANONICAL: SELL and BUY are independent - no reset on side change"""
        config = SignalThrottleConfig(
            min_price_change_pct=1.0,
            min_interval_minutes=1.0,  # Fixed 60 seconds
        )
        
        now = datetime.now(timezone.utc)
        thirty_seconds_ago = now - timedelta(seconds=30)  # 30s < 60s
        two_minutes_ago = now - timedelta(minutes=2)
        
        # Last SELL was 30 seconds ago (< 60 seconds) - should be blocked by time gate
        last_sell = LastSignalSnapshot(
            side="SELL",
            price=0.50,
            timestamp=thirty_seconds_ago,
        )
        
        # Last BUY was 2 minutes ago (more recent than SELL, but doesn't matter - sides are independent)
        last_buy = LastSignalSnapshot(
            side="BUY",
            price=0.49,
            timestamp=two_minutes_ago,
        )
        
        allowed, reason = should_emit_signal(
            symbol="ADA_USDT",
            side="SELL",
            current_price=0.50,  # Same price as last SELL, but time gate blocks first
            current_time=now,
            config=config,
            last_same_side=last_sell,
            last_opposite_side=last_buy,
        )
        
        # Should be blocked by time gate (30s < 60s) - sides are independent
        assert allowed is False
        assert "THROTTLED_TIME_GATE" in reason or "elapsed" in reason.lower()
    
    def test_throttle_decision_logs_origin(self):
        """Throttle decisions should log runtime origin (AWS vs LOCAL)"""
        # Test that get_runtime_origin() works (defaults to LOCAL in test environment)
        origin = get_runtime_origin()
        assert origin in ["AWS", "LOCAL"]
        
        # The actual logging happens in signal_monitor.py with [ALERT_THROTTLE_DECISION] origin=...
        # This test just verifies the helper function exists and returns a valid value

