"""Unit tests for Expected TP Details sign-normalized profit/loss display helpers."""

from decimal import Decimal

from app.models.exchange_order import OrderSideEnum
from app.services.expected_take_profit import (
    calculate_sl_display_loss,
    calculate_tp_display_profit,
)


def test_long_tp_profit_is_always_positive():
    amount, pct = calculate_tp_display_profit(
        OrderSideEnum.BUY,
        Decimal("100"),
        Decimal("110"),
        Decimal("2"),
    )
    assert amount == Decimal("20")
    assert pct == Decimal("10")
    assert amount > 0
    assert pct > 0


def test_short_tp_profit_is_always_positive():
    amount, pct = calculate_tp_display_profit(
        OrderSideEnum.SELL,
        Decimal("100"),
        Decimal("90"),
        Decimal("2"),
    )
    assert amount == Decimal("20")
    assert pct == Decimal("10")
    assert amount > 0
    assert pct > 0


def test_long_sl_loss_is_always_negative():
    amount, pct = calculate_sl_display_loss(
        OrderSideEnum.BUY,
        Decimal("100"),
        Decimal("95"),
        Decimal("2"),
    )
    assert amount == Decimal("-10")
    assert pct == Decimal("-5")
    assert amount < 0
    assert pct < 0


def test_short_sl_loss_is_always_negative():
    amount, pct = calculate_sl_display_loss(
        OrderSideEnum.SELL,
        Decimal("100"),
        Decimal("105"),
        Decimal("2"),
    )
    assert amount == Decimal("-10")
    assert pct == Decimal("-5")
    assert amount < 0
    assert pct < 0


def test_tp_display_normalizes_sign_when_raw_is_negative():
    # Defensive: if TP price were below entry, UI still shows positive magnitude.
    amount, pct = calculate_tp_display_profit(
        OrderSideEnum.BUY,
        Decimal("100"),
        Decimal("95"),
        Decimal("1"),
    )
    assert amount == Decimal("5")
    assert pct == Decimal("5")
    assert amount > 0


def test_sl_display_normalizes_sign_when_raw_is_positive():
    # Defensive: if SL price were above entry on a short, UI still shows negative magnitude.
    amount, pct = calculate_sl_display_loss(
        OrderSideEnum.SELL,
        Decimal("100"),
        Decimal("95"),
        Decimal("1"),
    )
    assert amount == Decimal("-5")
    assert pct == Decimal("-5")
    assert amount < 0
