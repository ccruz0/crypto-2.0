"""Tests for execution origin classification."""

import pytest

from app.utils.execution_origin import (
    EXECUTION_ORIGIN_ALERT,
    EXECUTION_ORIGIN_MANUAL,
    EXECUTION_ORIGIN_STOP_LOSS,
    EXECUTION_ORIGIN_TAKE_PROFIT,
    format_type_display,
    is_protection_execution,
    resolve_execution_origin,
)


@pytest.mark.parametrize(
    "order_role,order_type,parent_order_id,trade_signal_id,has_intent,has_signal,expected",
    [
        ("STOP_LOSS", "MARKET", None, None, False, False, EXECUTION_ORIGIN_STOP_LOSS),
        ("TAKE_PROFIT", "MARKET", None, None, False, False, EXECUTION_ORIGIN_TAKE_PROFIT),
        (None, "STOP_LIMIT", None, None, False, False, EXECUTION_ORIGIN_STOP_LOSS),
        (None, "TAKE_PROFIT_LIMIT", None, None, False, False, EXECUTION_ORIGIN_TAKE_PROFIT),
        (None, "MARKET", "parent-123", None, False, False, "EXCHANGE"),
        (None, "MARKET", None, 42, False, False, EXECUTION_ORIGIN_ALERT),
        (None, "MARKET", None, None, True, False, EXECUTION_ORIGIN_ALERT),
        (None, "MARKET", None, None, False, True, EXECUTION_ORIGIN_ALERT),
        (None, "MARKET", None, None, False, False, EXECUTION_ORIGIN_MANUAL),
        (None, "LIMIT", None, 99, False, False, EXECUTION_ORIGIN_ALERT),
    ],
)
def test_resolve_execution_origin(
    order_role,
    order_type,
    parent_order_id,
    trade_signal_id,
    has_intent,
    has_signal,
    expected,
):
    assert resolve_execution_origin(
        order_role=order_role,
        order_type=order_type,
        parent_order_id=parent_order_id,
        trade_signal_id=trade_signal_id,
        has_order_intent=has_intent,
        has_trade_signal_link=has_signal,
    ) == expected


def test_format_type_display_alert_market():
    assert format_type_display(order_type="MARKET", execution_origin=EXECUTION_ORIGIN_ALERT) == "MARKET (Alerta)"


def test_format_type_display_manual_limit():
    assert format_type_display(order_type="LIMIT", execution_origin=EXECUTION_ORIGIN_MANUAL) == "LIMIT (Manual)"


def test_format_type_display_sl_tp():
    assert format_type_display(order_type="MARKET", execution_origin=EXECUTION_ORIGIN_STOP_LOSS) == "SL ejecutado"
    assert format_type_display(order_type="MARKET", execution_origin=EXECUTION_ORIGIN_TAKE_PROFIT) == "TP ejecutado"


def test_is_protection_execution():
    assert is_protection_execution(order_role="STOP_LOSS") is True
    assert is_protection_execution(order_type="TAKE_PROFIT_LIMIT") is True
    assert is_protection_execution(execution_origin=EXECUTION_ORIGIN_ALERT) is False
