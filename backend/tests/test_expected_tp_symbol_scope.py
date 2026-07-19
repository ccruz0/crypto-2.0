"""Tests for Expected TP strict symbol scope and short (SELL) open lots."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import (
    OpenLot,
    build_entry_orders_details,
    get_expected_take_profit_details,
    get_expected_take_profit_summary,
    rebuild_open_lots,
    resolve_position_side,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[ExchangeOrder.__table__])
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=[ExchangeOrder.__table__])
        engine.dispose()


def _add_order(db_session, **kwargs) -> ExchangeOrder:
    now = kwargs.get("exchange_create_time") or datetime.now(timezone.utc)
    order = ExchangeOrder(
        exchange_order_id=kwargs["exchange_order_id"],
        symbol=kwargs.get("symbol", "ETH_USDT"),
        side=kwargs.get("side", OrderSideEnum.BUY),
        order_type=kwargs.get("order_type", "LIMIT"),
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        order_role=kwargs.get("order_role"),
        parent_order_id=kwargs.get("parent_order_id"),
        price=Decimal(str(kwargs.get("price", "70000"))),
        quantity=Decimal(str(kwargs.get("quantity", "0.05"))),
        cumulative_quantity=Decimal(str(kwargs.get("cumulative_quantity", kwargs.get("quantity", "0.05")))),
        cumulative_value=Decimal(str(kwargs.get("cumulative_value", "3500"))),
        avg_price=Decimal(str(kwargs.get("price", "70000"))),
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(order)
    db_session.commit()
    return order


def test_rebuild_open_lots_eth_usdt_excludes_eth_usd_book(db_session):
    """ETH_USDT scope must not pull in ETH_USD buys (PR #170 regression)."""
    t0 = datetime(2026, 7, 9, 17, 34, 16, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 13, 8, 0, 0, tzinfo=timezone.utc)

    _add_order(
        db_session,
        exchange_order_id="5755600491599559568",
        symbol="ETH_USD",
        side=OrderSideEnum.BUY,
        price="1740.5",
        quantity="0.0135",
        exchange_create_time=t0,
    )
    _add_order(
        db_session,
        exchange_order_id="5755600491711938017",
        symbol="ETH_USDT",
        side=OrderSideEnum.SELL,
        price="71362",
        quantity="0.05",
        exchange_create_time=t1,
    )

    lots = rebuild_open_lots(db_session, "ETH_USDT")
    assert len(lots) == 1
    assert lots[0].symbol == "ETH_USDT"
    assert lots[0].buy_order_id == "5755600491711938017"
    assert resolve_position_side(db_session, lots) == "SHORT"


def test_rebuild_open_lots_base_symbol_still_searches_quote_variants(db_session):
    _add_order(
        db_session,
        exchange_order_id="btc-buy",
        symbol="BTC_USDT",
        side=OrderSideEnum.BUY,
        price="60000",
        quantity="0.01",
    )
    lots = rebuild_open_lots(db_session, "BTC")
    assert len(lots) == 1
    assert lots[0].symbol == "BTC_USDT"


def test_short_lot_matches_buy_side_tp_via_parent(db_session):
    t_entry = datetime(2026, 7, 13, 8, 0, 0, tzinfo=timezone.utc)
    t_tp = datetime(2026, 7, 13, 8, 0, 5, tzinfo=timezone.utc)

    sell = _add_order(
        db_session,
        exchange_order_id="5755600491711938017",
        symbol="ETH_USDT",
        side=OrderSideEnum.SELL,
        price="71362",
        quantity="0.05",
        exchange_create_time=t_entry,
    )
    _add_order(
        db_session,
        exchange_order_id="tp-short-1",
        symbol="ETH_USDT",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="71363",
        quantity="0.05",
        parent_order_id=sell.exchange_order_id,
        exchange_create_time=t_tp,
    )

    details = get_expected_take_profit_details(
        db_session,
        "ETH_USDT",
        current_price=71300.0,
        portfolio_balance=-0.05,
    )

    assert details["position_side"] == "SHORT"
    assert len(details["entry_orders"]) == 1
    assert details["entry_orders"][0]["symbol"] == "ETH_USDT"
    assert details["entry_orders"][0]["side"] == "SELL"
    assert details["entry_orders"][0]["order_id"] == "5755600491711938017"
    assert details["entry_orders"][0]["take_profits"]


def test_summary_includes_negative_balance_short(db_session):
    t_entry = datetime(2026, 7, 13, 8, 0, 0, tzinfo=timezone.utc)
    sell = _add_order(
        db_session,
        exchange_order_id="5755600491711938017",
        symbol="ETH_USDT",
        side=OrderSideEnum.SELL,
        price="71362",
        quantity="0.05",
        exchange_create_time=t_entry,
    )
    _add_order(
        db_session,
        exchange_order_id="tp-short-1",
        symbol="ETH_USDT",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="70000",
        quantity="0.05",
        parent_order_id=sell.exchange_order_id,
    )

    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[
            {
                "coin": "ETH",
                "balance": -0.05,
                "value_usd": -3568.1,
            }
        ],
        market_prices={"ETH": 71362.0},
    )

    assert "ETH_USDT" in summary
    assert summary["ETH_USDT"]["position_side"] == "SHORT"
    assert summary["ETH_USDT"]["net_qty"] == pytest.approx(0.05)


def test_build_entry_orders_details_preserves_pair_symbol(db_session):
    buy = _add_order(
        db_session,
        exchange_order_id="5755600491599559568",
        side=OrderSideEnum.BUY,
        symbol="ETH_USD",
    )
    lots = [
        OpenLot(
            symbol="ETH_USD",
            buy_order_id=buy.exchange_order_id,
            buy_time=datetime.now(timezone.utc),
            buy_price=Decimal("1740.5"),
            lot_qty=Decimal("0.0135"),
        )
    ]
    entries = build_entry_orders_details(db_session, lots)
    assert entries[0]["symbol"] == "ETH_USD"


def test_cocreation_tests_use_db_mock():
    """Guard: match helpers require a Session (even a mock)."""
    from app.services.expected_take_profit import match_all_tp_orders

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    lot = OpenLot(
        symbol="BTC_USD",
        buy_order_id="buy-explicit",
        buy_time=datetime(2026, 7, 7, 6, 2, 50, tzinfo=timezone.utc),
        buy_price=Decimal("1"),
        lot_qty=Decimal("0.3"),
    )
    tp = ExchangeOrder(
        exchange_order_id="tp-explicit",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price=Decimal("2"),
        quantity=Decimal("0.3"),
        cumulative_quantity=Decimal("0"),
        parent_order_id="buy-explicit",
        exchange_create_time=datetime(2026, 7, 7, 6, 2, 53, tzinfo=timezone.utc),
        exchange_update_time=datetime(2026, 7, 7, 6, 2, 53, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 7, 6, 2, 53, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 7, 6, 2, 53, tzinfo=timezone.utc),
    )
    matched, unmatched = match_all_tp_orders(mock_db, [lot], [tp])
    assert len(matched) == 1


def test_protected_margin_sell_not_fifo_net_against_long_buys(db_session):
    """Margin SELL with OTOCO must stay a short lot even when long buys exist on the pair."""
    t_buy = datetime(2026, 5, 28, 5, 3, 14, tzinfo=timezone.utc)
    t_sell = datetime(2026, 7, 14, 11, 18, 26, tzinfo=timezone.utc)
    t_tp = datetime(2026, 7, 14, 11, 18, 27, tzinfo=timezone.utc)

    _add_order(
        db_session,
        exchange_order_id="5755600489289088548",
        symbol="BTC_USD",
        side=OrderSideEnum.BUY,
        price="71100",
        quantity="0.30",
        exchange_create_time=t_buy,
    )
    sell = _add_order(
        db_session,
        exchange_order_id="5755600491774711109",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        order_type="MARKET",
        price="62722.11",
        quantity="0.00015",
        exchange_create_time=t_sell,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490101973692",
        symbol="BTC_USD",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="62094.89",
        quantity="0.00015",
        cumulative_quantity="0",
        parent_order_id=sell.exchange_order_id,
        exchange_create_time=t_tp,
    )

    lots = rebuild_open_lots(db_session, "BTC_USD")
    short_lots = [lot for lot in lots if lot.buy_order_id == sell.exchange_order_id]
    assert len(short_lots) == 1
    assert short_lots[0].lot_qty == Decimal("0.00015")

    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[
            {
                "coin": "BTC",
                "balance": 2.49,
                "value_usd": 156000.0,
            }
        ],
        market_prices={"BTC": 62722.0, "BTC_USD": 62722.0},
    )

    # Hedged book: protected short + remaining long must be MIXED (not a short-only stub).
    btc_usd = summary.get("BTC_USD")
    assert btc_usd is not None
    assert btc_usd["position_side"] == "MIXED"
    assert btc_usd["entry_lot_count"] == 2
    assert btc_usd["net_qty"] == pytest.approx(0.30015)
    assert btc_usd["total_expected_profit"] == pytest.approx(0.094083)

    details = get_expected_take_profit_details(
        db_session,
        "BTC_USD",
        current_price=62722.0,
        portfolio_balance=2.49,
    )
    sell_entries = [
        entry
        for entry in details["entry_orders"]
        if entry["order_id"] == sell.exchange_order_id
    ]
    assert len(sell_entries) == 1
    assert sell_entries[0]["side"] == "SELL"
    assert sell_entries[0]["take_profits"]
    assert details["position_side"] == "MIXED"


def test_summary_eth_usd_mixed_not_short_only_stub(db_session):
    """Negative ETH balance must not drop the protected BUY long from ETH_USD summary."""
    t0 = datetime(2026, 7, 7, 2, 11, 33, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 9, 17, 34, 16, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 14, 13, 29, 8, tzinfo=timezone.utc)

    sell_a = _add_order(
        db_session,
        exchange_order_id="5755600491465274888",
        symbol="ETH_USD",
        side=OrderSideEnum.SELL,
        price="1790.66",
        quantity="0.0558",
        exchange_create_time=t0,
    )
    buy_long = _add_order(
        db_session,
        exchange_order_id="5755600491599559568",
        symbol="ETH_USD",
        side=OrderSideEnum.BUY,
        price="1740.5",
        quantity="0.0788",
        exchange_create_time=t1,
    )
    sell_b = _add_order(
        db_session,
        exchange_order_id="5755600491780783859",
        symbol="ETH_USD",
        side=OrderSideEnum.SELL,
        price="1876.73",
        quantity="0.0532",
        exchange_create_time=t2,
    )
    for parent, tp_id, tp_side, tp_price, qty in (
        (sell_a, "tp-eth-a", OrderSideEnum.BUY, "1736.52", "0.0558"),
        (buy_long, "tp-eth-long", OrderSideEnum.SELL, "1948.62", "0.0788"),
        (sell_b, "tp-eth-b", OrderSideEnum.BUY, "1857.96", "0.0532"),
    ):
        _add_order(
            db_session,
            exchange_order_id=tp_id,
            symbol="ETH_USD",
            side=tp_side,
            order_type="TAKE_PROFIT_LIMIT",
            order_role="TAKE_PROFIT",
            status=OrderStatusEnum.ACTIVE,
            price=tp_price,
            quantity=qty,
            cumulative_quantity="0",
            parent_order_id=parent.exchange_order_id,
        )

    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[
            {"coin": "ETH", "balance": -0.0302, "value_usd": -56.0},
        ],
        market_prices={"ETH": 1872.0, "ETH_USD": 1872.0},
    )

    eth_usd = summary.get("ETH_USD")
    assert eth_usd is not None
    assert eth_usd["position_side"] == "MIXED"
    assert eth_usd["entry_lot_count"] == 3
    assert eth_usd["net_qty"] == pytest.approx(0.1878)
    # Long TP dominates: (1948.62-1740.5)*0.0788 ≈ 16.40
    assert eth_usd["total_expected_profit"] > 16.0

    # Must not also emit a short-only duplicate row for the same pair.
    short_stubs = [
        row
        for key, row in summary.items()
        if row.get("symbol") == "ETH_USD" and row.get("position_side") == "SHORT"
    ]
    assert short_stubs == []


def test_summary_btc_usd_includes_large_long_tp_profit(db_session):
    """BTC_USD summary must count large MANUAL long TPs, not only micro short TPs."""
    t_long = datetime(2026, 6, 29, 14, 53, 44, tzinfo=timezone.utc)
    t_short = datetime(2026, 7, 14, 11, 18, 26, tzinfo=timezone.utc)

    buy = _add_order(
        db_session,
        exchange_order_id="5755600491091887888",
        symbol="BTC_USD",
        side=OrderSideEnum.BUY,
        price="59100",
        quantity="1.3",
        exchange_create_time=t_long,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490101952837",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="67000",
        quantity="1.3",
        cumulative_quantity="0",
        parent_order_id=buy.exchange_order_id,
        exchange_create_time=t_long,
    )
    sell = _add_order(
        db_session,
        exchange_order_id="5755600491774711109",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        order_type="MARKET",
        price="62722.11",
        quantity="0.00015",
        exchange_create_time=t_short,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490101973692",
        symbol="BTC_USD",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="62094.89",
        quantity="0.00015",
        cumulative_quantity="0",
        parent_order_id=sell.exchange_order_id,
        exchange_create_time=t_short,
    )
    # Unrelated BTC_USDT lot must not absorb BTC_USD into the USDT summary row.
    _add_order(
        db_session,
        exchange_order_id="usdt-buy-orphan",
        symbol="BTC_USDT",
        side=OrderSideEnum.BUY,
        price="75100",
        quantity="0.3",
        exchange_create_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )

    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[
            {"coin": "BTC", "balance": 2.5, "value_usd": 160000.0},
        ],
        market_prices={"BTC": 64425.0, "BTC_USD": 64425.0, "BTC_USDT": 64425.0},
    )

    btc_usd = summary.get("BTC_USD")
    assert btc_usd is not None
    assert btc_usd["position_side"] == "MIXED"
    assert btc_usd["entry_lot_count"] == 2
    # (67000-59100)*1.3 + (62722.11-62094.89)*0.00015 ≈ 10270.09
    assert btc_usd["total_expected_profit"] == pytest.approx(10270.094083, rel=1e-6)
    assert "BTC_USDT" in summary
    assert summary["BTC_USDT"]["symbol"] == "BTC_USDT"
    # No short-only stub alongside the MIXED row.
    assert not any(
        row.get("symbol") == "BTC_USD" and row.get("position_side") == "SHORT"
        for row in summary.values()
    )
