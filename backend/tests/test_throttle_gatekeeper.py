"""Tests for throttle gatekeeper - universal throttle enforcement."""
import pytest
from app.services.throttle_gatekeeper import enforce_throttle, log_throttle_decision


def test_enforce_throttle_allows_when_throttle_passed():
    """Test that gatekeeper allows when throttle check passed."""
    allowed, reason = enforce_throttle(
        symbol="BTC_USDT",
        side="BUY",
        current_price=50000.0,
        throttle_allowed=True,
        throttle_reason="cooldown OK (5.12m >= 5.00m)",
        throttle_metadata={
            "time_since_last": 5.12,
            "price_change_pct": 1.5,
            "blocked_by_time": False,
            "blocked_by_price": False,
        },
    )
    assert allowed is True
    assert "PASSED" in reason


def test_enforce_throttle_blocks_when_throttle_failed():
    """Test that gatekeeper blocks when throttle check failed."""
    allowed, reason = enforce_throttle(
        symbol="BTC_USDT",
        side="BUY",
        current_price=50000.0,
        throttle_allowed=False,
        throttle_reason="THROTTLED_TIME_GATE (elapsed 30.0s < 60.0s)",
        throttle_metadata={
            "time_since_last": 2.0,
            "price_change_pct": 0.3,
            "blocked_by_time": True,
            "blocked_by_price": False,
        },
    )
    assert allowed is False
    assert "FAILED" in reason


def test_enforce_throttle_blocks_btc_with_zero_price_change():
    """Test that gatekeeper blocks BTC with 0% price change."""
    allowed, reason = enforce_throttle(
        symbol="BTC_USDT",
        side="BUY",
        current_price=50000.0,
        throttle_allowed=False,
        throttle_reason="THROTTLED_PRICE_GATE (price change 0.00% < 1.00%)",
        throttle_metadata={
            "time_since_last": 10.0,
            "price_change_pct": 0.0,
            "blocked_by_time": False,
            "blocked_by_price": True,
        },
    )
    assert allowed is False
    assert "FAILED" in reason


def test_enforce_throttle_blocks_btc_with_insufficient_time():
    """Test that gatekeeper blocks BTC with insufficient time."""
    allowed, reason = enforce_throttle(
        symbol="BTC_USDT",
        side="BUY",
        current_price=50000.0,
        throttle_allowed=False,
        throttle_reason="THROTTLED_TIME_GATE (elapsed 30.0s < 60.0s)",
        throttle_metadata={
            "time_since_last": 1.0,
            "price_change_pct": 2.0,
            "blocked_by_time": True,
            "blocked_by_price": False,
        },
    )
    assert allowed is False
    assert "FAILED" in reason


def test_enforce_throttle_blocks_btc_both_conditions_fail():
    """Test that gatekeeper blocks BTC when both time and price fail."""
    allowed, reason = enforce_throttle(
        symbol="BTC_USDT",
        side="BUY",
        current_price=50000.0,
        throttle_allowed=False,
        throttle_reason="THROTTLED_TIME_GATE (elapsed 30.0s < 60.0s)",
        throttle_metadata={
            "time_since_last": 2.0,
            "price_change_pct": 0.05,
            "blocked_by_time": True,
            "blocked_by_price": True,
        },
    )
    assert allowed is False
    assert "FAILED" in reason


def test_enforce_throttle_allows_when_both_conditions_met():
    """Test that gatekeeper allows when both time and price conditions are met."""
    allowed, reason = enforce_throttle(
        symbol="BTC_USDT",
        side="BUY",
        current_price=51000.0,
        throttle_allowed=True,
        throttle_reason="cooldown OK (6.00m >= 5.00m) AND price change 2.00% >= 1.00%",
        throttle_metadata={
            "time_since_last": 6.0,
            "price_change_pct": 2.0,
            "blocked_by_time": False,
            "blocked_by_price": False,
        },
    )
    assert allowed is True
    assert "PASSED" in reason


def test_log_throttle_decision(caplog):
    """Test that throttle decision logging works."""
    with caplog.at_level("INFO"):
        log_throttle_decision(
            symbol="BTC_USDT",
            side="BUY",
            current_price=50000.0,
            throttle_allowed=True,
            throttle_reason="cooldown OK",
            throttle_metadata={
                "time_since_last": 5.12,
                "price_change_pct": 1.5,
            },
        )
    
    assert "[THROTTLE_DECISION]" in caplog.text
    assert "BTC_USDT" in caplog.text
    assert "allowed=True" in caplog.text


def test_enforce_throttle_handles_missing_metadata():
    """Test that gatekeeper handles missing metadata gracefully."""
    allowed, reason = enforce_throttle(
        symbol="BTC_USDT",
        side="BUY",
        current_price=50000.0,
        throttle_allowed=True,
        throttle_reason="No previous signal",
        throttle_metadata=None,
    )
    assert allowed is True
    assert "PASSED" in reason


class TestBTCThrottleStressScenario:
    """Test the 4-tick stress scenario that mimics production behavior."""
    
    def test_tick1_first_alert_allowed(self):
        """Tick 1: First alert should be allowed (no previous signal)."""
        allowed, reason = enforce_throttle(
            symbol="BTC_USDT",
            side="BUY",
            current_price=50000.0,
            throttle_allowed=True,
            throttle_reason="No previous same-side signal recorded",
            throttle_metadata={
                "time_since_last": None,
                "price_change_pct": None,
                "blocked_by_time": False,
                "blocked_by_price": False,
            },
        )
        assert allowed is True, f"First alert should be allowed, got reason: {reason}"
        assert "PASSED" in reason
    
    def test_tick2_blocked_insufficient_time_and_price(self):
        """Tick 2: 10 seconds later, 0% change → must be BLOCKED."""
        allowed, reason = enforce_throttle(
            symbol="BTC_USDT",
            side="BUY",
            current_price=50000.0,
            throttle_allowed=False,
            throttle_reason="THROTTLED_TIME_GATE (elapsed 10.0s < 60.0s)",
            throttle_metadata={
                "time_since_last": 0.17,  # 10 seconds = 0.17 minutes
                "price_change_pct": 0.0,
                "blocked_by_time": True,
                "blocked_by_price": True,
            },
        )
        assert allowed is False, f"Second alert should be blocked, got reason: {reason}"
        assert "FAILED" in reason
    
    def test_tick3_blocked_insufficient_price_change(self):
        """Tick 3: 40 seconds later, 0.02% change → must be BLOCKED."""
        allowed, reason = enforce_throttle(
            symbol="BTC_USDT",
            side="BUY",
            current_price=50010.0,
            throttle_allowed=False,
            throttle_reason="THROTTLED_MIN_CHANGE (price change 0.02% < 1.00%)",
            throttle_metadata={
                "time_since_last": 0.67,  # 40 seconds = 0.67 minutes
                "price_change_pct": 0.02,
                "blocked_by_time": False,
                "blocked_by_price": True,
            },
        )
        assert allowed is False, f"Third alert should be blocked, got reason: {reason}"
        assert "FAILED" in reason
    
    def test_tick4_allowed_sufficient_time_and_price(self):
        """Tick 4: 6 minutes later, 2% change → must be ALLOWED."""
        allowed, reason = enforce_throttle(
            symbol="BTC_USDT",
            side="BUY",
            current_price=51000.0,
            throttle_allowed=True,
            throttle_reason="cooldown OK (6.00m >= 5.00m) AND price change 2.00% >= 1.00%",
            throttle_metadata={
                "time_since_last": 6.0,
                "price_change_pct": 2.0,
                "blocked_by_time": False,
                "blocked_by_price": False,
            },
        )
        assert allowed is True, f"Fourth alert should be allowed, got reason: {reason}"
        assert "PASSED" in reason
    
    def test_full_4_tick_sequence(self):
        """Test the complete 4-tick sequence in order."""
        # Tick 1: First alert (allowed)
        allowed1, reason1 = enforce_throttle(
            symbol="BTC_USDT",
            side="BUY",
            current_price=50000.0,
            throttle_allowed=True,
            throttle_reason="No previous same-side signal recorded",
            throttle_metadata=None,
        )
        assert allowed1 is True
        
        # Tick 2: 10 seconds later, same price (blocked)
        allowed2, reason2 = enforce_throttle(
            symbol="BTC_USDT",
            side="BUY",
            current_price=50000.0,
            throttle_allowed=False,
            throttle_reason="THROTTLED_TIME_GATE (elapsed 10.0s < 60.0s)",
            throttle_metadata={
                "time_since_last": 0.17,
                "price_change_pct": 0.0,
                "blocked_by_time": True,
                "blocked_by_price": False,
            },
        )
        assert allowed2 is False
        
        # Tick 3: 40 seconds later, small price change (blocked)
        allowed3, reason3 = enforce_throttle(
            symbol="BTC_USDT",
            side="BUY",
            current_price=50010.0,
            throttle_allowed=False,
            throttle_reason="THROTTLED_MIN_CHANGE (price change 0.02% < 1.00%)",
            throttle_metadata={
                "time_since_last": 0.67,
                "price_change_pct": 0.02,
                "blocked_by_time": False,
                "blocked_by_price": True,
            },
        )
        assert allowed3 is False
        
        # Tick 4: 6 minutes later, sufficient price change (allowed)
        allowed4, reason4 = enforce_throttle(
            symbol="BTC_USDT",
            side="BUY",
            current_price=51000.0,
            throttle_allowed=True,
            throttle_reason="cooldown OK (6.00m >= 5.00m) AND price change 2.00% >= 1.00%",
            throttle_metadata={
                "time_since_last": 6.0,
                "price_change_pct": 2.0,
                "blocked_by_time": False,
                "blocked_by_price": False,
            },
        )
        assert allowed4 is True
        
        # Verify sequence: allow, block, block, allow
        assert [allowed1, allowed2, allowed3, allowed4] == [True, False, False, True]

