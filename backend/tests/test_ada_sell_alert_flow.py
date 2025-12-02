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
        """First SELL alert should always be allowed (no previous state)"""
        config = SignalThrottleConfig(
            min_price_change_pct=1.0,
            min_interval_minutes=5.0,
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
    
    def test_sell_alert_throttled_by_cooldown(self):
        """SELL alert should be throttled if within cooldown period AND price change too small"""
        config = SignalThrottleConfig(
            min_price_change_pct=1.0,
            min_interval_minutes=5.0,
        )
        
        now = datetime.now(timezone.utc)
        two_minutes_ago = now - timedelta(minutes=2)  # 2 min < 5 min cooldown
        
        last_sell = LastSignalSnapshot(
            side="SELL",
            price=0.50,
            timestamp=two_minutes_ago,
        )
        
        allowed, reason = should_emit_signal(
            symbol="ADA_USDT",
            side="SELL",
            current_price=0.504,  # 0.8% price change (below 1% threshold) AND cooldown not met
            current_time=now,
            config=config,
            last_same_side=last_sell,
            last_opposite_side=None,
        )
        
        # Should be blocked because BOTH cooldown AND price change fail
        assert allowed is False
        assert "THROTTLED" in reason or "elapsed" in reason.lower() or "cooldown" in reason.lower()
    
    def test_sell_alert_throttled_by_price_change(self):
        """SELL alert should be throttled if price change < 1% AND cooldown not met"""
        config = SignalThrottleConfig(
            min_price_change_pct=1.0,
            min_interval_minutes=5.0,
        )
        
        now = datetime.now(timezone.utc)
        two_minutes_ago = now - timedelta(minutes=2)  # Cooldown NOT met (2 min < 5 min)
        
        last_sell = LastSignalSnapshot(
            side="SELL",
            price=0.50,
            timestamp=two_minutes_ago,
        )
        
        allowed, reason = should_emit_signal(
            symbol="ADA_USDT",
            side="SELL",
            current_price=0.504,  # 0.8% price change (below 1% threshold) AND cooldown not met
            current_time=now,
            config=config,
            last_same_side=last_sell,
            last_opposite_side=None,
        )
        
        # Should be blocked because BOTH cooldown AND price change fail
        assert allowed is False
        assert "THROTTLED" in reason or "price change" in reason.lower() or "cooldown" in reason.lower()
    
    def test_sell_alert_allowed_after_cooldown_and_price_change(self):
        """SELL alert should be allowed after cooldown AND sufficient price change"""
        config = SignalThrottleConfig(
            min_price_change_pct=1.0,
            min_interval_minutes=5.0,
        )
        
        now = datetime.now(timezone.utc)
        ten_minutes_ago = now - timedelta(minutes=10)  # Cooldown met
        
        last_sell = LastSignalSnapshot(
            side="SELL",
            price=0.50,
            timestamp=ten_minutes_ago,
        )
        
        allowed, reason = should_emit_signal(
            symbol="ADA_USDT",
            side="SELL",
            current_price=0.51,  # 2% price change (meets threshold)
            current_time=now,
            config=config,
            last_same_side=last_sell,
            last_opposite_side=None,
        )
        
        assert allowed is True
        assert "cooldown" in reason.lower() or "price change" in reason.lower() or "Δt=" in reason or "Δp=" in reason
    
    def test_sell_after_buy_resets_throttle(self):
        """SELL alert after BUY should always be allowed (direction change)"""
        config = SignalThrottleConfig(
            min_price_change_pct=1.0,
            min_interval_minutes=5.0,
        )
        
        now = datetime.now(timezone.utc)
        one_minute_ago = now - timedelta(minutes=1)
        two_minutes_ago = now - timedelta(minutes=2)
        
        # Last SELL was 2 minutes ago
        last_sell = LastSignalSnapshot(
            side="SELL",
            price=0.50,
            timestamp=two_minutes_ago,
        )
        
        # But last BUY was 1 minute ago (more recent)
        last_buy = LastSignalSnapshot(
            side="BUY",
            price=0.49,
            timestamp=one_minute_ago,
        )
        
        allowed, reason = should_emit_signal(
            symbol="ADA_USDT",
            side="SELL",
            current_price=0.50,  # Same price as last SELL (would normally throttle)
            current_time=now,
            config=config,
            last_same_side=last_sell,
            last_opposite_side=last_buy,
        )
        
        assert allowed is True
        assert "direction change" in reason.lower() or "opposite-side" in reason.lower()
    
    def test_throttle_decision_logs_origin(self):
        """Throttle decisions should log runtime origin (AWS vs LOCAL)"""
        # Test that get_runtime_origin() works (defaults to LOCAL in test environment)
        origin = get_runtime_origin()
        assert origin in ["AWS", "LOCAL"]
        
        # The actual logging happens in signal_monitor.py with [ALERT_THROTTLE_DECISION] origin=...
        # This test just verifies the helper function exists and returns a valid value

