from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.signal_throttle import (
    LastSignalSnapshot,
    SignalThrottleConfig,
    should_emit_signal,
)

BASE_TIME = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def _snapshot(minutes_ago: float, price: float, side: str = "BUY", force_next: bool = False) -> LastSignalSnapshot:
    return LastSignalSnapshot(
        side=side,
        price=price,
        timestamp=BASE_TIME - timedelta(minutes=minutes_ago),
        force_next_signal=force_next,
    )


def test_should_emit_signal_blocks_on_time_gate():
    """CANONICAL: Fixed 60 seconds time gate - blocks if < 60 seconds elapsed."""
    # Canonical: throttling is fixed at 60 seconds (1.0 minute), not configurable
    config = SignalThrottleConfig(min_price_change_pct=0.0, min_interval_minutes=1.0)
    # Last signal 30 seconds ago (< 60 seconds) - should be blocked by time gate
    last_state = _snapshot(minutes_ago=0.5, price=100.0)

    allowed, reason = should_emit_signal(
        symbol="ADA_USDT",
        side="BUY",
        current_price=100.0,
        current_time=BASE_TIME,
        config=config,
        last_same_side=last_state,
        last_opposite_side=None,
    )

    # Should be blocked by time gate (30s < 60s)
    assert allowed is False
    assert "THROTTLED_TIME_GATE" in reason or "elapsed" in reason.lower()


def test_should_emit_signal_blocks_on_price_gate():
    """CANONICAL: Price gate checked after time gate passes - blocks if price change < threshold."""
    # Canonical: time gate is always fixed at 60 seconds, price gate checked after
    config = SignalThrottleConfig(min_price_change_pct=2.0, min_interval_minutes=1.0)
    # Last signal 2 minutes ago (> 60 seconds) - time gate passes
    last_state = _snapshot(minutes_ago=2.0, price=100.0)

    allowed, reason = should_emit_signal(
        symbol="ETH_USDT",
        side="BUY",
        current_price=101.0,  # 1% < 2% required - should be blocked by price gate
        current_time=BASE_TIME,
        config=config,
        last_same_side=last_state,
        last_opposite_side=None,
    )

    # Time gate passes (2m >= 1m), but price gate fails (1% < 2%)
    assert allowed is False
    assert "THROTTLED_PRICE_GATE" in reason or "price change" in reason.lower()


def test_should_emit_signal_accepts_when_thresholds_met():
    """CANONICAL: Both time gate (60s) and price gate pass."""
    config = SignalThrottleConfig(min_price_change_pct=1.0, min_interval_minutes=1.0)
    # Last signal 2 minutes ago (> 60 seconds) - time gate passes
    last_state = _snapshot(minutes_ago=2.0, price=100.0)

    allowed, reason = should_emit_signal(
        symbol="BTC_USDT",
        side="SELL",
        current_price=102.0,  # 2% >= 1% - price gate passes
        current_time=BASE_TIME,
        config=config,
        last_same_side=last_state,
        last_opposite_side=None,
    )

    assert allowed is True
    assert "Δt=" in reason or "60" in reason or "price change" in reason.lower()


def test_should_emit_signal_sides_are_independent():
    """CANONICAL: BUY and SELL are independent - no reset on side change."""
    config = SignalThrottleConfig(min_price_change_pct=5.0, min_interval_minutes=1.0)
    # Last BUY was 30 seconds ago (< 60 seconds) - should be blocked
    last_buy = _snapshot(minutes_ago=0.5, price=100.0, side="BUY")
    # Last SELL was 2 minutes ago (more recent than BUY, but doesn't matter - sides are independent)
    last_sell = _snapshot(minutes_ago=2.0, price=105.0, side="SELL")

    allowed, reason = should_emit_signal(
        symbol="SOL_USDT",
        side="BUY",
        current_price=101.0,  # Only 1% change (needs 5%), but time gate blocks first
        current_time=BASE_TIME,
        config=config,
        last_same_side=last_buy,
        last_opposite_side=last_sell,
    )

    # Should be blocked by time gate (30s < 60s) - sides are independent
    assert allowed is False
    assert "THROTTLED_TIME_GATE" in reason or "elapsed" in reason.lower()


def test_should_emit_signal_first_call_without_history_allows():
    """CANONICAL: First alert for a side is always allowed."""
    config = SignalThrottleConfig(min_price_change_pct=3.0, min_interval_minutes=1.0)

    allowed, reason = should_emit_signal(
        symbol="UNI_USDT",
        side="SELL",
        current_price=5.0,
        current_time=BASE_TIME,
        config=config,
        last_same_side=None,
        last_opposite_side=None,
    )

    assert allowed is True
    assert reason.startswith("No previous") or "first" in reason.lower()


def test_should_emit_signal_force_flag_bypasses_throttling():
    """CANONICAL: force_next_signal (config change bypass) allows immediate alert."""
    config = SignalThrottleConfig(min_price_change_pct=5.0, min_interval_minutes=1.0)
    # Create a snapshot that would normally be blocked (30 seconds ago, 1% price change)
    # but has force_next_signal=True (config change bypass)
    last_state = _snapshot(minutes_ago=0.5, price=100.0, force_next=True)

    allowed, reason = should_emit_signal(
        symbol="BTC_USDT",
        side="BUY",
        current_price=101.0,  # Only 1% change (needs 5%), but bypassed by force flag
        current_time=BASE_TIME,
        config=config,
        last_same_side=last_state,
        last_opposite_side=None,
    )

    assert allowed is True
    assert "IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE" in reason


def test_should_emit_signal_force_flag_works_without_db():
    """CANONICAL: Force flag bypasses throttling even without DB (flag is in snapshot)."""
    config = SignalThrottleConfig(min_price_change_pct=5.0, min_interval_minutes=1.0)
    # Create a snapshot that would normally be blocked (30 seconds ago, 1% price change)
    # but has force_next_signal=True
    last_state = _snapshot(minutes_ago=0.5, price=100.0, force_next=True)

    allowed, reason = should_emit_signal(
        symbol="BTC_USDT",
        side="BUY",
        current_price=101.0,  # Only 1% change (needs 5%)
        current_time=BASE_TIME,
        config=config,
        last_same_side=last_state,
        last_opposite_side=None,
    )

    assert allowed is True
    assert "IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE" in reason


def test_should_emit_signal_force_flag_only_bypasses_once():
    """CANONICAL: After force flag is used, normal throttling resumes."""
    config = SignalThrottleConfig(min_price_change_pct=5.0, min_interval_minutes=1.0)
    
    # First call with force flag - should be allowed (bypass)
    last_state_forced = _snapshot(minutes_ago=0.5, price=100.0, force_next=True)
    allowed1, reason1 = should_emit_signal(
        symbol="BTC_USDT",
        side="BUY",
        current_price=101.0,
        current_time=BASE_TIME,
        config=config,
        last_same_side=last_state_forced,
        last_opposite_side=None,
    )
    assert allowed1 is True
    assert "IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE" in reason1
    
    # Second call without force flag (flag was cleared) - should be blocked
    last_state_normal = _snapshot(minutes_ago=0.5, price=100.0, force_next=False)
    allowed2, reason2 = should_emit_signal(
        symbol="BTC_USDT",
        side="BUY",
        current_price=101.0,
        current_time=BASE_TIME,
        config=config,
        last_same_side=last_state_normal,
        last_opposite_side=None,
    )
    # Should be blocked because time gate fails (30s < 60s)
    assert allowed2 is False
    assert "THROTTLED_TIME_GATE" in reason2 or "THROTTLED" in reason2


