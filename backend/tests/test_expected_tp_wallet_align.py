"""Expected TP must align net_qty to wallet truth (not stale FIFO lot sums)."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import (
    get_expected_take_profit_details,
    get_expected_take_profit_summary,
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
    qty = kwargs.get("quantity", "0.05")
    order = ExchangeOrder(
        exchange_order_id=kwargs["exchange_order_id"],
        symbol=kwargs.get("symbol", "BTC_USD"),
        side=kwargs.get("side", OrderSideEnum.BUY),
        order_type=kwargs.get("order_type", "LIMIT"),
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        order_role=kwargs.get("order_role"),
        parent_order_id=kwargs.get("parent_order_id"),
        price=Decimal(str(kwargs.get("price", "70000"))),
        quantity=Decimal(str(qty)),
        cumulative_quantity=Decimal(str(kwargs.get("cumulative_quantity", qty))),
        cumulative_value=Decimal(str(kwargs.get("cumulative_value", "0"))),
        avg_price=Decimal(str(kwargs.get("price", "70000"))),
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(order)
    db_session.commit()
    return order


def test_btc_oversize_lots_capped_to_wallet_across_sister_books(db_session):
    """BTC-like: FIFO lots > wallet must not inflate; sister books share one wallet."""
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 2, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 3, 1, tzinfo=timezone.utc)

    buy_usd = _add_order(
        db_session,
        exchange_order_id="btc-usd-buy",
        symbol="BTC_USD",
        side=OrderSideEnum.BUY,
        price="60000",
        quantity="2.0",
        exchange_create_time=t0,
    )
    _add_order(
        db_session,
        exchange_order_id="btc-usd-tp",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="70000",
        quantity="2.0",
        cumulative_quantity="0",
        parent_order_id=buy_usd.exchange_order_id,
        exchange_create_time=t0,
    )
    # Tiny protected short keeps MIXED on USD book (like prod).
    sell_micro = _add_order(
        db_session,
        exchange_order_id="btc-usd-short",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        price="62000",
        quantity="0.001",
        exchange_create_time=t1,
    )
    _add_order(
        db_session,
        exchange_order_id="btc-usd-short-tp",
        symbol="BTC_USD",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="61000",
        quantity="0.001",
        cumulative_quantity="0",
        parent_order_id=sell_micro.exchange_order_id,
        exchange_create_time=t1,
    )
    buy_usdt = _add_order(
        db_session,
        exchange_order_id="btc-usdt-buy",
        symbol="BTC_USDT",
        side=OrderSideEnum.BUY,
        price="61000",
        quantity="0.5",
        exchange_create_time=t2,
    )
    _add_order(
        db_session,
        exchange_order_id="btc-usdt-tp",
        symbol="BTC_USDT",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="72000",
        quantity="0.5",
        cumulative_quantity="0",
        parent_order_id=buy_usdt.exchange_order_id,
        exchange_create_time=t2,
    )

    wallet = Decimal("1.893")
    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[{"coin": "BTC", "balance": float(wallet), "value_usd": 120000.0}],
        market_prices={"BTC": 64000.0, "BTC_USD": 64000.0, "BTC_USDT": 64000.0},
    )

    btc_rows = [row for key, row in summary.items() if str(key).startswith("BTC_")]
    assert btc_rows
    total_net = sum(float(row["net_qty"]) for row in btc_rows)
    assert total_net == pytest.approx(float(wallet), rel=1e-6)
    for row in btc_rows:
        assert float(row["net_qty"]) <= float(wallet) + 1e-9
        assert row.get("wallet_qty_warning") == "lots_exceed_wallet"

    details = get_expected_take_profit_details(
        db_session,
        "BTC_USD",
        current_price=64000.0,
        portfolio_balance=float(wallet),
    )
    assert details["net_qty"] == pytest.approx(float(wallet))
    assert details["net_qty"] <= float(wallet) + 1e-9


def test_dgb_ghost_short_dropped_when_wallet_long(db_session):
    """DGB-like: stale SELL lots must not create a huge SHORT vs long wallet."""
    t0 = datetime(2026, 1, 15, tzinfo=timezone.utc)
    ghost = _add_order(
        db_session,
        exchange_order_id="dgb-ghost-sell",
        symbol="DGB_USD",
        side=OrderSideEnum.SELL,
        price="0.004",
        quantity="332700",
        exchange_create_time=t0,
    )
    _add_order(
        db_session,
        exchange_order_id="dgb-ghost-tp",
        symbol="DGB_USD",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="0.0035",
        quantity="332700",
        cumulative_quantity="0",
        parent_order_id=ghost.exchange_order_id,
        exchange_create_time=t0,
    )

    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[{"coin": "DGB", "balance": 4028.0, "value_usd": 14.0}],
        market_prices={"DGB": 0.0034, "DGB_USD": 0.0034},
    )

    dgb_rows = [row for row in summary.values() if str(row.get("symbol", "")).startswith("DGB")]
    assert dgb_rows == []
    assert not any(float(row.get("net_qty") or 0) > 10000 for row in summary.values())


def test_doge_short_path_uses_abs_wallet_not_pair_qty(db_session):
    """DOGE-like: short path must use |wallet|, not sum of stale MIXED lots."""
    t0 = datetime(2026, 4, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    long_buy = _add_order(
        db_session,
        exchange_order_id="doge-long",
        symbol="DOGE_USD",
        side=OrderSideEnum.BUY,
        price="0.08",
        quantity="8000",
        exchange_create_time=t0,
    )
    _add_order(
        db_session,
        exchange_order_id="doge-long-tp",
        symbol="DOGE_USD",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="0.10",
        quantity="8000",
        cumulative_quantity="0",
        parent_order_id=long_buy.exchange_order_id,
        exchange_create_time=t0,
    )
    short_sell = _add_order(
        db_session,
        exchange_order_id="doge-short",
        symbol="DOGE_USD",
        side=OrderSideEnum.SELL,
        price="0.09",
        quantity="1187",
        exchange_create_time=t1,
    )
    _add_order(
        db_session,
        exchange_order_id="doge-short-tp",
        symbol="DOGE_USD",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="0.07",
        quantity="1187",
        cumulative_quantity="0",
        parent_order_id=short_sell.exchange_order_id,
        exchange_create_time=t1,
    )

    wallet = -559.0
    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[{"coin": "DOGE", "balance": wallet, "value_usd": -40.0}],
        market_prices={"DOGE": 0.07, "DOGE_USD": 0.07},
    )

    doge = summary.get("DOGE_USD")
    assert doge is not None
    assert doge["net_qty"] == pytest.approx(abs(wallet))
    assert doge["net_qty"] < 1000  # not the inflated 9187 lot sum
    assert doge.get("wallet_qty_warning") == "lots_exceed_wallet"
