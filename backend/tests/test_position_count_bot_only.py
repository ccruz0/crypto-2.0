"""Guardrail position counts must include bot orders only, not manual/synced holdings."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.watchlist import WatchlistItem
from app.services.order_position_service import count_open_positions_for_symbol
from app.services.system_core_trade_guards import count_distinct_symbols_with_open_positions


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    for table in Base.metadata.tables.values():
        try:
            table.create(bind=engine, checkfirst=True)
        except OperationalError as exc:
            if "already exists" not in str(exc).lower():
                raise

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _order(
    *,
    exchange_order_id: str,
    symbol: str = "BTC_USD",
    side: OrderSideEnum = OrderSideEnum.BUY,
    status: OrderStatusEnum = OrderStatusEnum.FILLED,
    qty: str = "1",
    trade_signal_id: int | None = None,
    parent_order_id: str | None = None,
    order_role: str | None = None,
) -> ExchangeOrder:
    return ExchangeOrder(
        exchange_order_id=exchange_order_id,
        symbol=symbol,
        side=side,
        order_type="MARKET",
        status=status,
        price=Decimal("100000"),
        quantity=Decimal(qty),
        cumulative_quantity=Decimal(qty),
        avg_price=Decimal("100000"),
        exchange_create_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        trade_signal_id=trade_signal_id,
        parent_order_id=parent_order_id,
        order_role=order_role,
    )


def test_manual_filled_buy_does_not_count(db_session):
    db_session.add(_order(exchange_order_id="manual_buy_1", trade_signal_id=None))
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "BTC") == 0


def test_bot_filled_buy_counts(db_session):
    db_session.add(_order(exchange_order_id="bot_buy_1", trade_signal_id=101))
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "BTC") == 1


def test_bot_buy_closed_by_protection_sell_counts_zero(db_session):
    db_session.add(_order(exchange_order_id="bot_buy_2", trade_signal_id=102, qty="1"))
    db_session.add(
        _order(
            exchange_order_id="bot_tp_1",
            side=OrderSideEnum.SELL,
            trade_signal_id=102,
            parent_order_id="bot_buy_2",
            order_role="TAKE_PROFIT",
            qty="1",
        )
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "BTC") == 0


def test_manual_sell_does_not_offset_bot_buy(db_session):
    db_session.add(_order(exchange_order_id="bot_buy_3", trade_signal_id=103, qty="1"))
    db_session.add(
        _order(
            exchange_order_id="manual_sell_1",
            side=OrderSideEnum.SELL,
            trade_signal_id=None,
            parent_order_id=None,
            order_role=None,
            qty="1",
        )
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "BTC") == 1


def test_distinct_symbols_ignores_manual_only_holdings(db_session):
    db_session.add_all(
        [
            WatchlistItem(symbol="BTC_USD", exchange="CRYPTO_COM", is_deleted=False),
            WatchlistItem(symbol="ETH_USDT", exchange="CRYPTO_COM", is_deleted=False),
            _order(exchange_order_id="manual_btc_1", trade_signal_id=None),
            _order(
                exchange_order_id="bot_eth_1",
                symbol="ETH_USDT",
                trade_signal_id=201,
                qty="0.1",
            ),
        ]
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "BTC") == 0
    assert count_open_positions_for_symbol(db_session, "ETH") == 1
    assert count_distinct_symbols_with_open_positions(db_session) == 1
