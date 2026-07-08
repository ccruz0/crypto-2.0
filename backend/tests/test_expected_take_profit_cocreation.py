"""Unit tests for OTOCO co-creation inference in expected_take_profit matching."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.models.exchange_order import OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import (
    OpenLot,
    match_all_tp_orders,
    match_tp_orders_by_cocreation,
)


def _tp(
    order_id: str,
    symbol: str,
    quantity: str,
    *,
    parent_order_id=None,
    create_time: datetime,
):
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
        parent_order_id=parent_order_id,
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


def test_cocreation_matches_tp_to_co_created_buy_with_same_qty():
    """DOGE-like case: one TP co-created with the 133-qty buy, not the 130-qty lots."""
    t0 = datetime(2026, 7, 6, 17, 40, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 6, 17, 50, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 7, 6, 2, 50, tzinfo=timezone.utc)
    tp_time = datetime(2026, 7, 7, 6, 2, 53, tzinfo=timezone.utc)

    lots = [
        _lot("buy-130a", "DOGE_USD", "130", t0),
        _lot("buy-130b", "DOGE_USD", "130", t1),
        _lot("buy-133", "DOGE_USD", "133", t2),
    ]
    tp = _tp("tp-133", "DOGE_USD", "133", create_time=tp_time)

    matched, unmatched, remaining = match_tp_orders_by_cocreation(lots, [tp])

    assert len(matched) == 1
    assert matched[0].buy_order_id == "buy-133"
    assert matched[0].matched_tp.exchange_order_id == "tp-133"
    assert matched[0].match_origin == "OTOCO"
    assert len(unmatched) == 2
    assert remaining == []


def test_cocreation_skips_when_parent_order_id_already_set():
    t_buy = datetime(2026, 7, 7, 6, 2, 50, tzinfo=timezone.utc)
    t_tp = datetime(2026, 7, 7, 6, 2, 53, tzinfo=timezone.utc)
    lot = _lot("buy-linked", "DOGE_USD", "133", t_buy)
    tp = _tp(
        "tp-linked",
        "DOGE_USD",
        "133",
        parent_order_id="other-parent",
        create_time=t_tp,
    )

    matched, unmatched, remaining = match_tp_orders_by_cocreation([lot], [tp])

    assert matched == []
    assert unmatched == [lot]
    assert remaining == [tp]


def test_match_all_prefers_explicit_parent_over_cocreation():
    t_buy = datetime(2026, 7, 7, 6, 2, 50, tzinfo=timezone.utc)
    t_tp = datetime(2026, 7, 7, 6, 2, 53, tzinfo=timezone.utc)
    lot = _lot("buy-explicit", "BTC_USD", "0.3", t_buy)
    tp = _tp(
        "tp-explicit",
        "BTC_USD",
        "0.3",
        parent_order_id="buy-explicit",
        create_time=t_tp,
    )

    matched, unmatched = match_all_tp_orders([lot], [tp])

    assert len(matched) == 1
    assert matched[0].buy_order_id == "buy-explicit"
    assert unmatched == []
