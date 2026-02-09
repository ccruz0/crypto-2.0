"""
Week 6: Tests for exchange formatting layer (Decimal, no scientific notation, quantize, trigger_condition).
"""
import pytest
from decimal import Decimal

from app.core.exchange_formatting_week6 import (
    normalize_decimal_str,
    quantize_price,
    quantize_qty,
    validate_price_tick,
    validate_qty_step,
    format_trigger_condition,
    classify_exchange_error_code,
    operator_action_for_api_disabled,
    REASON_INVALID_PRICE_FORMAT,
    REASON_EXCHANGE_API_DISABLED,
    EXCHANGE_CODE_INVALID_PRICE_FORMAT,
    EXCHANGE_CODE_API_DISABLED,
)


def test_normalize_decimal_str_no_scientific():
    assert "1e" not in normalize_decimal_str(Decimal("0.0001"))
    assert "1E" not in normalize_decimal_str(Decimal("0.0001"))
    assert normalize_decimal_str(Decimal("2954.86")) == "2954.86"
    assert normalize_decimal_str(Decimal("2984.4086")) == "2984.4086"


def test_normalize_decimal_str_no_commas():
    s = normalize_decimal_str(Decimal("1234.56"))
    assert "," not in s
    assert s == "1234.56"


def test_normalize_decimal_str_trailing_zeros():
    # Strip trailing zeros after decimal
    assert normalize_decimal_str(Decimal("100.00")) == "100"
    assert normalize_decimal_str(Decimal("100.10")) == "100.1"
    assert normalize_decimal_str(Decimal("0.0033"), max_dp=4) == "0.0033"


def test_normalize_decimal_str_max_dp():
    assert normalize_decimal_str(Decimal("1.23456789"), max_dp=4) == "1.2346"
    assert normalize_decimal_str(Decimal("1.2"), max_dp=2) == "1.2"


def test_quantize_price():
    meta = {"price_tick_size": "0.01"}
    assert quantize_price(meta, Decimal("2984.4086"), round_up=False) == Decimal("2984.40")
    assert quantize_price(meta, Decimal("2984.4086"), round_up=True) == Decimal("2984.41")
    meta4 = {"price_tick_size": "0.0001"}
    assert quantize_price(meta4, Decimal("2954.8600"), round_up=False) == Decimal("2954.86")


def test_quantize_qty():
    meta = {"qty_tick_size": "0.001", "min_quantity": "0.001"}
    assert quantize_qty(meta, Decimal("0.0033")) == Decimal("0.003")
    meta2 = {"qty_tick_size": "0.1"}
    assert quantize_qty(meta2, Decimal("1.23")) == Decimal("1.2")


def test_validate_price_tick_ok():
    meta = {"price_tick_size": "0.01"}
    validate_price_tick(meta, Decimal("2984.41"))


def test_validate_price_tick_raises():
    meta = {"price_tick_size": "0.01"}
    with pytest.raises(ValueError, match="not aligned to tick"):
        validate_price_tick(meta, Decimal("2984.405"))


def test_validate_qty_step_below_min_raises():
    meta = {"qty_tick_size": "0.001", "min_quantity": "0.01"}
    with pytest.raises(ValueError, match="below min_quantity"):
        validate_qty_step(meta, Decimal("0.005"))


def test_validate_qty_step_aligned_ok():
    meta = {"qty_tick_size": "0.001", "min_quantity": "0.001"}
    validate_qty_step(meta, Decimal("0.003"))


def test_format_trigger_condition_tp():
    tc = format_trigger_condition("TP", Decimal("2984.4086"), ">=")
    assert tc == ">= 2984.4086"
    assert "e" not in tc.lower() and "E" not in tc


def test_format_trigger_condition_sl():
    tc = format_trigger_condition("SL", Decimal("2659.374"), "<=")
    assert tc == "<= 2659.374"


def test_classify_exchange_error_308():
    assert classify_exchange_error_code(308) == REASON_INVALID_PRICE_FORMAT
    assert classify_exchange_error_code(EXCHANGE_CODE_INVALID_PRICE_FORMAT) == REASON_INVALID_PRICE_FORMAT


def test_classify_exchange_error_140001():
    assert classify_exchange_error_code(140001) == REASON_EXCHANGE_API_DISABLED
    assert classify_exchange_error_code(EXCHANGE_CODE_API_DISABLED) == REASON_EXCHANGE_API_DISABLED


def test_classify_exchange_error_other():
    assert classify_exchange_error_code(400) is None
    assert classify_exchange_error_code(None) is None


def test_operator_action_for_api_disabled():
    msg = operator_action_for_api_disabled()
    assert "API" in msg or "conditional" in msg or "permissions" in msg
    assert "CRYPTOCOM" in msg or "docs" in msg
