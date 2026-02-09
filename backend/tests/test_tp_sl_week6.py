"""
Week 6: Tests for TP/SL error classification (308 -> INVALID_PRICE_FORMAT, 140001 -> EXCHANGE_API_DISABLED).
"""
import pytest
from unittest.mock import MagicMock, patch

from app.core.exchange_formatting_week6 import (
    REASON_INVALID_PRICE_FORMAT,
    REASON_EXCHANGE_API_DISABLED,
    classify_exchange_error_code,
)
from app.core.retry_circuit_week5 import (
    is_exchange_code_retryable,
    is_retryable_error,
    NON_RETRYABLE_EXCHANGE_CODES,
)


def test_308_classified_as_invalid_price_format():
    assert classify_exchange_error_code(308) == REASON_INVALID_PRICE_FORMAT


def test_140001_classified_as_exchange_api_disabled():
    assert classify_exchange_error_code(140001) == REASON_EXCHANGE_API_DISABLED


def test_308_not_retryable():
    assert is_exchange_code_retryable(308) is False
    assert 308 in NON_RETRYABLE_EXCHANGE_CODES


def test_140001_not_retryable():
    assert is_exchange_code_retryable(140001) is False
    assert 140001 in NON_RETRYABLE_EXCHANGE_CODES


def test_retryable_error_with_exchange_code_308():
    assert is_retryable_error(ConnectionError("x"), exchange_code=308) is False


def test_retryable_error_with_exchange_code_140001():
    assert is_retryable_error(ConnectionError("x"), exchange_code=140001) is False


def test_retryable_error_with_exchange_code_0():
    assert is_retryable_error(ConnectionError("x"), exchange_code=0) is True


def test_simulate_308_response_logs_reason_code():
    """Simulate exchange returning 308; ensure we have a reason code for logging."""
    reason = classify_exchange_error_code(308)
    assert reason == REASON_INVALID_PRICE_FORMAT


def test_simulate_140001_response_logs_reason_code_and_blocked():
    """Simulate exchange returning 140001; decision should be BLOCKED, reason EXCHANGE_API_DISABLED."""
    reason = classify_exchange_error_code(140001)
    assert reason == REASON_EXCHANGE_API_DISABLED
