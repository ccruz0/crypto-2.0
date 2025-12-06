from decimal import Decimal

from app.services.open_orders import (
    calculate_portfolio_order_metrics,
    merge_orders,
)


def test_merge_orders_normalizes_payloads():
    normal = [
        {
            "order_id": "1",
            "instrument_name": "BTC_USDT",
            "side": "BUY",
            "order_type": "LIMIT",
            "limit_price": "50000",
            "quantity": "0.5",
            "status": "ACTIVE",
        }
    ]
    triggers = [
        {
            "order_id": "2",
            "instrument_name": "BTC_USDT",
            "side": "SELL",
            "order_type": "TAKE_PROFIT_LIMIT",
            "trigger_price": "60000",
            "quantity": "0.5",
            "status": "NEW",
        }
    ]

    merged = merge_orders(normal, triggers)
    assert len(merged) == 2
    buy = next(order for order in merged if order.side == "BUY")
    assert buy.price == Decimal("50000")
    sell = next(order for order in merged if order.side == "SELL")
    assert sell.is_trigger is True
    assert sell.trigger_price == Decimal("60000")


def test_portfolio_metrics_calculates_tp_sl():
    orders = merge_orders(
        [
            {"order_id": "1", "instrument_name": "ETH_USDT", "side": "BUY", "order_type": "LIMIT", "limit_price": "3000", "quantity": "1"},
        ],
        [
            {"order_id": "2", "instrument_name": "ETH_USDT", "side": "SELL", "order_type": "TAKE_PROFIT_LIMIT", "trigger_price": "3500", "quantity": "1"},
            {"order_id": "3", "instrument_name": "ETH_USDT", "side": "SELL", "order_type": "STOP_LIMIT", "trigger_price": "2500", "quantity": "1"},
        ],
    )

    metrics = calculate_portfolio_order_metrics(orders)
    assert "ETH" in metrics
    assert metrics["ETH"]["count"] == 3
    assert metrics["ETH"]["tp"] == Decimal("3500")
    assert metrics["ETH"]["sl"] == Decimal("2500")

