"""
Week 5: Tests for trading safety invariants (fail-fast).
"""
import pytest
from app.core.trading_invariants_week5 import (
    validate_symbol_and_side,
    validate_quantity,
    validate_price_format,
    validate_tp_sl_requires_fill,
    validate_sell_position_exists,
    validate_trading_decision,
    InvariantFailure,
    REASON_INVALID_SYMBOL,
    REASON_INVALID_SIDE,
    REASON_INVALID_QUANTITY,
    REASON_INVALID_PRICE,
    REASON_TP_SL_REQUIRES_FILL,
    REASON_SELL_REQUIRES_POSITION,
)


def test_validate_symbol_and_side_valid():
    assert validate_symbol_and_side("BTC_USDT", "BUY", "c1") is None
    assert validate_symbol_and_side("ETH_USDT", "SELL", "c2") is None


def test_validate_symbol_and_side_invalid_symbol():
    fail = validate_symbol_and_side("", "BUY", "c1")
    assert fail is not None
    assert isinstance(fail, InvariantFailure)
    assert fail.reason_code == REASON_INVALID_SYMBOL


def test_validate_symbol_and_side_invalid_side():
    fail = validate_symbol_and_side("BTC_USDT", "INVALID", "c1")
    assert fail is not None
    assert fail.reason_code == REASON_INVALID_SIDE


def test_validate_quantity_valid():
    assert validate_quantity(1.0, "BTC_USDT", "c1") is None
    assert validate_quantity(0.001, "ETH_USDT", "c1") is None


def test_validate_quantity_invalid():
    assert validate_quantity(0, "BTC_USDT", "c1") is not None
    assert validate_quantity(-1, "BTC_USDT", "c1") is not None
    assert validate_quantity(None, "BTC_USDT", "c1") is not None
    fail = validate_quantity(0, "BTC_USDT", "c1")
    assert fail.reason_code == REASON_INVALID_QUANTITY


def test_validate_price_format_valid():
    assert validate_price_format(100.5, "BTC_USDT", "c1") is None
    assert validate_price_format(0.001, "ETH_USDT", "c1") is None
    assert validate_price_format(None, "BTC_USDT", "c1", allow_none=True) is None


def test_validate_price_format_invalid():
    assert validate_price_format(None, "BTC_USDT", "c1", allow_none=False) is not None
    assert validate_price_format(-1, "BTC_USDT", "c1") is not None
    fail = validate_price_format("x", "BTC_USDT", "c1")
    assert fail is not None
    assert fail.reason_code == REASON_INVALID_PRICE


def test_validate_tp_sl_requires_fill_not_requested():
    assert validate_tp_sl_requires_fill(False, None, None, "BTC_USDT", "c1") is None


def test_validate_tp_sl_requires_fill_requested_with_fill():
    assert validate_tp_sl_requires_fill(True, 100.0, 1.0, "BTC_USDT", "c1") is None


def test_validate_tp_sl_requires_fill_requested_without_fill():
    fail = validate_tp_sl_requires_fill(True, None, 1.0, "BTC_USDT", "c1")
    assert fail is not None
    assert fail.reason_code == REASON_TP_SL_REQUIRES_FILL
    fail2 = validate_tp_sl_requires_fill(True, 100.0, None, "BTC_USDT", "c1")
    assert fail2 is not None


def test_validate_sell_position_exists_buy_ignored():
    assert validate_sell_position_exists("BUY", False, "BTC_USDT", "c1") is None


def test_validate_sell_position_exists_sell_with_position():
    assert validate_sell_position_exists("SELL", True, "BTC_USDT", "c1") is None


def test_validate_sell_position_exists_sell_without_position():
    fail = validate_sell_position_exists("SELL", False, "BTC_USDT", "c1")
    assert fail is not None
    assert fail.reason_code == REASON_SELL_REQUIRES_POSITION


def test_validate_trading_decision_full_valid():
    assert (
        validate_trading_decision(
            "BTC_USDT",
            "BUY",
            100.0,
            "c1",
            position_exists=None,
        )
        is None
    )
    assert (
        validate_trading_decision(
            "ETH_USDT",
            "SELL",
            1.0,
            "c2",
            position_exists=True,
        )
        is None
    )


def test_validate_trading_decision_fails_on_invalid_side():
    fail = validate_trading_decision("BTC_USDT", "X", 1.0, "c1")
    assert fail is not None
    assert fail.reason_code == REASON_INVALID_SIDE


def test_validate_trading_decision_fails_on_zero_quantity():
    fail = validate_trading_decision("BTC_USDT", "BUY", 0, "c1")
    assert fail is not None
    assert fail.reason_code == REASON_INVALID_QUANTITY


def test_validate_trading_decision_sell_fails_without_position():
    fail = validate_trading_decision(
        "BTC_USDT",
        "SELL",
        1.0,
        "c1",
        position_exists=False,
    )
    assert fail is not None
    assert fail.reason_code == REASON_SELL_REQUIRES_POSITION
