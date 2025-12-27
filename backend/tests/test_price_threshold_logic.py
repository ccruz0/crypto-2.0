"""
Unit tests for price threshold logic to verify $3, $10, $11, and "no limit" behavior.
These tests validate the throttle logic without requiring a running database.
"""
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from datetime import datetime, timedelta, timezone
from app.services.signal_throttle import (
    should_emit_signal,
    SignalThrottleConfig,
    LastSignalSnapshot,
)


def test_price_threshold_10_percent():
    """Test that 10% threshold blocks signals below 10% and allows signals >= 10%"""
    config = SignalThrottleConfig(min_price_change_pct=10.0, min_interval_minutes=1.0)
    now = datetime.now(timezone.utc)
    last_time = now - timedelta(seconds=65)  # 65 seconds ago (past time gate)
    last_price = 100.0
    current_price_9_5 = 109.5  # 9.5% increase
    current_price_10_5 = 110.5  # 10.5% increase
    
    last_snapshot = LastSignalSnapshot(
        symbol="TEST",
        side="BUY",
        timestamp=last_time,
        price=last_price,
        strategy_key="swing-conservative"
    )
    
    # Test 1: 9.5% change should be BLOCKED by 10% threshold
    allowed, reason = should_emit_signal(
        symbol="TEST",
        side="BUY",
        current_price=current_price_9_5,
        current_time=now,
        config=config,
        last_same_side=last_snapshot,
        last_opposite_side=None,
        db=None,
        strategy_key="swing-conservative"
    )
    assert not allowed, f"9.5% change should be blocked by 10% threshold, but got: {reason}"
    assert "THROTTLED_PRICE_GATE" in reason, f"Expected THROTTLED_PRICE_GATE, got: {reason}"
    print("✅ Test 1 passed: 9.5% change correctly blocked by 10% threshold")
    
    # Test 2: 10.5% change should be ALLOWED by 10% threshold
    allowed, reason = should_emit_signal(
        symbol="TEST",
        side="BUY",
        current_price=current_price_10_5,
        current_time=now,
        config=config,
        last_same_side=last_snapshot,
        last_opposite_side=None,
        db=None,
        strategy_key="swing-conservative"
    )
    assert allowed, f"10.5% change should pass 10% threshold, but got: {reason}"
    assert "10.5%" in reason or "10.50%" in reason, f"Expected price change in reason, got: {reason}"
    print("✅ Test 2 passed: 10.5% change correctly allowed by 10% threshold")


def test_price_threshold_11_percent():
    """Test that 11% threshold blocks signals below 11% and allows signals >= 11%"""
    config = SignalThrottleConfig(min_price_change_pct=11.0, min_interval_minutes=1.0)
    now = datetime.now(timezone.utc)
    last_time = now - timedelta(seconds=65)
    last_price = 100.0
    current_price_10_5 = 110.5  # 10.5% increase (should be blocked)
    current_price_11_2 = 111.2  # 11.2% increase (should pass)
    
    last_snapshot = LastSignalSnapshot(
        symbol="TEST",
        side="BUY",
        timestamp=last_time,
        price=last_price,
        strategy_key="swing-conservative"
    )
    
    # Test 1: 10.5% change should be BLOCKED by 11% threshold
    allowed, reason = should_emit_signal(
        symbol="TEST",
        side="BUY",
        current_price=current_price_10_5,
        current_time=now,
        config=config,
        last_same_side=last_snapshot,
        last_opposite_side=None,
        db=None,
        strategy_key="swing-conservative"
    )
    assert not allowed, f"10.5% change should be blocked by 11% threshold, but got: {reason}"
    assert "THROTTLED_PRICE_GATE" in reason, f"Expected THROTTLED_PRICE_GATE, got: {reason}"
    print("✅ Test 3 passed: 10.5% change correctly blocked by 11% threshold")
    
    # Test 2: 11.2% change should be ALLOWED by 11% threshold
    allowed, reason = should_emit_signal(
        symbol="TEST",
        side="BUY",
        current_price=current_price_11_2,
        current_time=now,
        config=config,
        last_same_side=last_snapshot,
        last_opposite_side=None,
        db=None,
        strategy_key="swing-conservative"
    )
    assert allowed, f"11.2% change should pass 11% threshold, but got: {reason}"
    print("✅ Test 4 passed: 11.2% change correctly allowed by 11% threshold")


def test_price_threshold_3_percent():
    """Test that 3% threshold blocks signals below 3% and allows signals >= 3%"""
    config = SignalThrottleConfig(min_price_change_pct=3.0, min_interval_minutes=1.0)
    now = datetime.now(timezone.utc)
    last_time = now - timedelta(seconds=65)
    last_price = 100.0
    current_price_2_9 = 102.9  # 2.9% increase (should be blocked)
    current_price_3_1 = 103.1  # 3.1% increase (should pass)
    
    last_snapshot = LastSignalSnapshot(
        symbol="TEST",
        side="BUY",
        timestamp=last_time,
        price=last_price,
        strategy_key="swing-conservative"
    )
    
    # Test 1: 2.9% change should be BLOCKED by 3% threshold
    allowed, reason = should_emit_signal(
        symbol="TEST",
        side="BUY",
        current_price=current_price_2_9,
        current_time=now,
        config=config,
        last_same_side=last_snapshot,
        last_opposite_side=None,
        db=None,
        strategy_key="swing-conservative"
    )
    assert not allowed, f"2.9% change should be blocked by 3% threshold, but got: {reason}"
    assert "THROTTLED_PRICE_GATE" in reason, f"Expected THROTTLED_PRICE_GATE, got: {reason}"
    print("✅ Test 5 passed: 2.9% change correctly blocked by 3% threshold")
    
    # Test 2: 3.1% change should be ALLOWED by 3% threshold
    allowed, reason = should_emit_signal(
        symbol="TEST",
        side="BUY",
        current_price=current_price_3_1,
        current_time=now,
        config=config,
        last_same_side=last_snapshot,
        last_opposite_side=None,
        db=None,
        strategy_key="swing-conservative"
    )
    assert allowed, f"3.1% change should pass 3% threshold, but got: {reason}"
    print("✅ Test 6 passed: 3.1% change correctly allowed by 3% threshold")


def test_no_limit_threshold():
    """Test that 0% threshold (no limit) allows any price change"""
    config = SignalThrottleConfig(min_price_change_pct=0.0, min_interval_minutes=1.0)
    now = datetime.now(timezone.utc)
    last_time = now - timedelta(seconds=65)
    last_price = 100.0
    current_price_minimal = 100.1  # 0.1% increase (should pass with no limit)
    
    last_snapshot = LastSignalSnapshot(
        symbol="TEST",
        side="BUY",
        timestamp=last_time,
        price=last_price,
        strategy_key="swing-conservative"
    )
    
    # Test: 0.1% change should be ALLOWED with 0% threshold (no limit)
    allowed, reason = should_emit_signal(
        symbol="TEST",
        side="BUY",
        current_price=current_price_minimal,
        current_time=now,
        config=config,
        last_same_side=last_snapshot,
        last_opposite_side=None,
        db=None,
        strategy_key="swing-conservative"
    )
    assert allowed, f"0.1% change should pass 0% threshold (no limit), but got: {reason}"
    print("✅ Test 7 passed: 0.1% change correctly allowed with 0% threshold (no limit)")


def test_time_gate_takes_precedence():
    """Test that time gate is checked first, even if price change is sufficient"""
    config = SignalThrottleConfig(min_price_change_pct=10.0, min_interval_minutes=1.0)
    now = datetime.now(timezone.utc)
    last_time = now - timedelta(seconds=30)  # Only 30 seconds ago (should block)
    last_price = 100.0
    current_price = 111.0  # 11% increase (sufficient, but time gate should block)
    
    last_snapshot = LastSignalSnapshot(
        symbol="TEST",
        side="BUY",
        timestamp=last_time,
        price=last_price,
        strategy_key="swing-conservative"
    )
    
    allowed, reason = should_emit_signal(
        symbol="TEST",
        side="BUY",
        current_price=current_price,
        current_time=now,
        config=config,
        last_same_side=last_snapshot,
        last_opposite_side=None,
        db=None,
        strategy_key="swing-conservative"
    )
    assert not allowed, f"Should be blocked by time gate, but got: {reason}"
    assert "THROTTLED_TIME_GATE" in reason, f"Expected THROTTLED_TIME_GATE, got: {reason}"
    print("✅ Test 8 passed: Time gate correctly takes precedence over price gate")


def run_all_tests():
    """Run all price threshold tests"""
    print("=" * 60)
    print("Running Price Threshold Logic Tests")
    print("=" * 60)
    
    try:
        test_price_threshold_10_percent()
        test_price_threshold_11_percent()
        test_price_threshold_3_percent()
        test_no_limit_threshold()
        test_time_gate_takes_precedence()
        
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return True
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

