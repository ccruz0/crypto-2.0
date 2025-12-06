from decimal import Decimal

import pytest

from app.services.open_orders import (
    calculate_portfolio_order_metrics,
    merge_orders,
)


def build_order(**overrides):
    base = {
        "order_id": overrides.get("order_id", "order-1"),
        "instrument_name": overrides.get("instrument_name", "BTC_USDT"),
        "side": overrides.get("side", "BUY"),
        "order_type": overrides.get("order_type", "LIMIT"),
        "limit_price": overrides.get("limit_price", "50000"),
        "quantity": overrides.get("quantity", "0.1"),
        "status": overrides.get("status", "ACTIVE"),
        "create_time": overrides.get("create_time", 1700000000000),
        "update_time": overrides.get("update_time", 1700000001000),
    }
    base.update(overrides)
    return base


def test_merge_orders_deduplicates_and_prefers_trigger_metadata():
    normal = [build_order(order_id="abc-1", limit_price="30000")]
    trigger = [
        build_order(
            order_id="abc-1",
            order_type="TAKE_PROFIT_LIMIT",
            trigger_price="32000",
            side="SELL",
        )
    ]

    merged = merge_orders(normal, trigger)
    assert len(merged) == 1
    unified = merged[0]
    assert unified.order_id == "abc-1"
    assert unified.is_trigger is True
    assert unified.trigger_price == Decimal("32000")


def test_calculate_portfolio_metrics_picks_highest_tp_and_lowest_sl():
    orders = merge_orders(
        [],
        [
            build_order(order_id="tp-high", side="SELL", trigger_price="100000", instrument_name="BTC_USDT", order_type="TAKE_PROFIT_LIMIT"),
            build_order(order_id="sl-low", side="SELL", trigger_price="90000", instrument_name="BTC_USDT", order_type="STOP_LIMIT"),
        ],
    )
    metrics = calculate_portfolio_order_metrics(orders)
    assert metrics["BTC"]["tp"] == pytest.approx(100000.0)
    assert metrics["BTC"]["sl"] == pytest.approx(90000.0)
    assert metrics["BTC"]["open_orders_count"] == 2


def test_partial_fill_preserves_status_and_quantity():
    trigger = [
        build_order(
            order_id="partial-1",
            side="SELL",
            order_type="TAKE_PROFIT_LIMIT",
            trigger_price="35000",
            quantity="1.0",
            cumulative_quantity="0.4",
            status="ACTIVE",
        )
    ]
    merged = merge_orders([], trigger)
    assert len(merged) == 1
    order = merged[0]
    assert order.quantity == Decimal("1.0")
    assert order.status == "ACTIVE"


@pytest.mark.parametrize(
    "regular,trigger,expected_len",
    [
        ([], [], 0),
        ([{}], [], 0),
        ([], [{}], 0),
    ],
)
def test_merge_orders_handles_empty_and_malformed_inputs(regular, trigger, expected_len):
    merged = merge_orders(regular, trigger)
    assert len(merged) == expected_len

