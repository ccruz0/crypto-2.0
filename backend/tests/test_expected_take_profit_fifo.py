"""Unit tests for FIFO fallback matching in expected_take_profit."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.models.exchange_order import OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import OpenLot, match_tp_orders_fifo


def _tp(order_id: str, symbol: str, quantity: str, *, create_time: datetime):
    return SimpleNamespace(
        exchange_order_id=order_id,
        symbol=symbol,
        side=OrderSideEnum.SELL,
        status=OrderStatusEnum.ACTIVE,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        quantity=Decimal(quantity),
        cumulative_quantity=Decimal("0"),
        price=Decimal("1"),
        parent_order_id=None,
        exchange_create_time=create_time,
        created_at=create_time,
    )


def _lot(buy_id: str, symbol: str, qty: str, buy_time: datetime):
    return OpenLot(
        symbol=symbol,
        buy_order_id=buy_id,
        buy_time=buy_time,
        buy_price=Decimal("1"),
        lot_qty=Decimal(qty),
    )


def test_fifo_prefers_exact_qty_lot_over_partial_accumulation():
    """
    BTC case: TP 0.141020 should match BUY 5755600483779731942 exactly,
    not two earlier partial lots whose sum also equals 0.141020.
    """
    t0 = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 3, 10, 0, 0, tzinfo=timezone.utc)
    tp_time = datetime(2026, 7, 3, 10, 0, 5, tzinfo=timezone.utc)

    lots = [
        _lot("5755600483779731900", "BTC_USD", "0.050000", t0),
        _lot("5755600483779731910", "BTC_USD", "0.091020", t1),
        _lot("5755600483779731942", "BTC_USD", "0.141020", t2),
    ]
    tp = _tp("73817490101969014", "BTC_USD", "0.141020", create_time=tp_time)

    result = match_tp_orders_fifo(lots, [tp])

    matched = [lot for lot in result if lot.matched_tp is not None]
    assert len(matched) == 1
    assert matched[0].buy_order_id == "5755600483779731942"
    assert matched[0].matched_tp.exchange_order_id == "73817490101969014"
    assert matched[0].match_origin == "FIFO"

    unmatched = [lot for lot in result if lot.matched_tp is None]
    assert len(unmatched) == 2
    assert {lot.buy_order_id for lot in unmatched} == {
        "5755600483779731900",
        "5755600483779731910",
    }
