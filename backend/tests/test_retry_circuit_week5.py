"""
Week 5: Tests for bounded retries and circuit breaker.
"""
import pytest
from unittest.mock import MagicMock

from app.core.retry_circuit_week5 import (
    is_retryable_error,
    retry_with_backoff,
    CircuitBreaker,
    get_exchange_circuit,
    get_telegram_circuit,
)


def test_retryable_error_network():
    assert is_retryable_error(ConnectionError("timeout")) is True
    assert is_retryable_error(OSError("network")) is True


def test_non_retryable_error_value():
    assert is_retryable_error(ValueError("bad")) is False
    assert is_retryable_error(TypeError("x")) is False


def test_non_retryable_http_codes():
    assert is_retryable_error(Exception(), http_code=401) is False
    assert is_retryable_error(Exception(), http_code=404) is False
    assert is_retryable_error(Exception(), http_code=422) is False


def test_retry_stops_after_max_attempts():
    call_count = 0
    def fail():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("fail")
    with pytest.raises(RuntimeError):
        retry_with_backoff(fail, max_attempts=3, base_delay=0.01, jitter=0.001, max_delay=0.1)
    assert call_count == 3


def test_non_retryable_does_not_retry():
    call_count = 0
    def fail_value():
        nonlocal call_count
        call_count += 1
        raise ValueError("bad")
    with pytest.raises(ValueError):
        retry_with_backoff(fail_value, max_attempts=3, base_delay=0.01)
    assert call_count == 1


def test_retry_succeeds_on_second_attempt():
    call_count = 0
    def succeed_second():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ConnectionError("temp")
        return 42
    result = retry_with_backoff(succeed_second, max_attempts=3, base_delay=0.01, jitter=0)
    assert result == 42
    assert call_count == 2


def test_circuit_opens_after_threshold():
    cb = CircuitBreaker("test", failure_threshold=3, window_minutes=5.0, cooldown_minutes=0.05)
    assert cb.allow_call() is True
    cb.record_failure()
    cb.record_failure()
    assert cb.allow_call() is True
    cb.record_failure()
    assert cb.is_open() is True
    assert cb.allow_call() is False
    assert cb.state() == "OPEN"


def test_circuit_closes_after_cooldown():
    import time
    cb = CircuitBreaker("test", failure_threshold=2, window_minutes=5.0, cooldown_minutes=0.02)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open() is True
    time.sleep(2.5)  # 0.02 min = 1.2 sec, wait 2.5 to be safe
    assert cb.is_open() is False
    assert cb.allow_call() is True
    assert cb.state() == "CLOSED"


def test_circuit_success_resets():
    cb = CircuitBreaker("test", failure_threshold=2, window_minutes=5.0, cooldown_minutes=1.0)
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert cb.allow_call() is True
    cb.record_failure()
    assert cb.is_open() is True


def test_get_exchange_circuit_singleton():
    c1 = get_exchange_circuit()
    c2 = get_exchange_circuit()
    assert c1 is c2


def test_get_telegram_circuit_singleton():
    c1 = get_telegram_circuit()
    c2 = get_telegram_circuit()
    assert c1 is c2
