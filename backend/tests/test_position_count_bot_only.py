"""Guardrail position count: bot orders only, including short entries."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.order_position_service import (
    count_open_positions_for_symbol,
    count_open_short_positions_for_symbol,
    count_total_open_positions,
)

BOT_SIGNAL_ID = 2001


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[ExchangeOrder.__table__])
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=[ExchangeOrder.__table__])
        engine.dispose()


def _bot_order(**kwargs) -> ExchangeOrder:
    now = datetime.now(timezone.utc)
    return ExchangeOrder(
        exchange_order_id=kwargs.get("exchange_order_id", f"ord_{now.timestamp()}"),
        client_oid=None,
        symbol=kwargs.get("symbol", "ETH_USDT"),
        side=kwargs.get("side", OrderSideEnum.BUY),
        order_type="MARKET",
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        price=Decimal("3000"),
        quantity=kwargs.get("quantity", Decimal("1")),
        cumulative_quantity=kwargs.get("cumulative_quantity", kwargs.get("quantity", Decimal("1"))),
        cumulative_value=Decimal("3000"),
        avg_price=Decimal("3000"),
        trigger_condition=None,
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
        imported_at=None,
        trade_signal_id=kwargs.get("trade_signal_id", BOT_SIGNAL_ID),
        parent_order_id=kwargs.get("parent_order_id", None),
        oco_group_id=None,
        order_role=kwargs.get("order_role", None),
    )


def test_manual_orders_excluded_from_count(db_session):
    """Exchange-synced orders without trade_signal_id must not affect guardrails."""
    manual = _bot_order(
        exchange_order_id="manual_buy",
        side=OrderSideEnum.BUY,
        trade_signal_id=None,
    )
    db_session.add(manual)
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH_USDT") == 0


def test_bot_short_entry_counts_for_guardrail(db_session):
    """Filled bot SELL entry is one open short position for maxOpenOrdersPerCoin."""
    db_session.add(
        _bot_order(
            exchange_order_id="short_eth_1",
            side=OrderSideEnum.SELL,
        )
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH_USDT") == 1


def test_second_short_on_same_symbol_would_exceed_per_coin_cap(db_session):
    """Two filled short entries on one symbol => count 2 (guard max=1 would block)."""
    db_session.add_all(
        [
            _bot_order(
                exchange_order_id="short_eth_1",
                side=OrderSideEnum.SELL,
                trade_signal_id=BOT_SIGNAL_ID,
            ),
            _bot_order(
                exchange_order_id="short_eth_2",
                side=OrderSideEnum.SELL,
                trade_signal_id=BOT_SIGNAL_ID + 1,
            ),
        ]
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH_USDT") == 2


def test_protection_sell_not_counted_as_short_position(db_session):
    db_session.add(
        _bot_order(
            exchange_order_id="tp_sell",
            side=OrderSideEnum.SELL,
            order_role="TAKE_PROFIT",
            trade_signal_id=None,
            parent_order_id="some_buy",
        )
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH_USDT") == 0


def test_bot_long_entry_unchanged(db_session):
    db_session.add(
        _bot_order(
            exchange_order_id="long_eth_1",
            side=OrderSideEnum.BUY,
        )
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH_USDT") == 1


def test_total_ignores_orphan_pending_take_profits(db_session):
    """Pending TP legs must not inflate MAX_OPEN_ORDERS_TOTAL (prod had 39 TPs / ~10 bot)."""
    # Orphan / protection TPs with no live bot entry
    db_session.add_all(
        [
            _bot_order(
                exchange_order_id="orphan_tp_btc_1",
                symbol="BTC_USD",
                side=OrderSideEnum.SELL,
                status=OrderStatusEnum.ACTIVE,
                order_role="TAKE_PROFIT",
                trade_signal_id=None,
                parent_order_id="old_buy_1",
            ),
            _bot_order(
                exchange_order_id="orphan_tp_btc_2",
                symbol="BTC_USD",
                side=OrderSideEnum.SELL,
                status=OrderStatusEnum.ACTIVE,
                order_role="TAKE_PROFIT",
                trade_signal_id=None,
                parent_order_id="old_buy_2",
            ),
        ]
    )
    db_session.commit()

    assert count_total_open_positions(db_session) == 0


def _twin_close_pair(symbol, parent_id, side, qty, role="STOP_LOSS"):
    """Two rows for ONE economic TP/SL fill: OCO trigger + spot remap.

    Reproduces the Crypto.com dual-ID behaviour recorded in #523 (ALGO stop
    persisted as 73817490102095276 and 5755600493106121990, same quantity,
    same second).
    """
    now = datetime.now(timezone.utc)
    trigger = _bot_order(
        exchange_order_id=f"73817490{parent_id}",
        symbol=symbol,
        side=side,
        order_role=role,
        trade_signal_id=None,
        parent_order_id=parent_id,
        quantity=qty,
        cumulative_quantity=qty,
    )
    trigger.oco_group_id = f"oco_{parent_id}_1"
    trigger.cumulative_value = Decimal("500")
    trigger.exchange_create_time = now
    trigger.exchange_update_time = now

    spot_remap = _bot_order(
        exchange_order_id=f"57556004{parent_id}",
        symbol=symbol,
        side=side,
        order_role=role,
        trade_signal_id=None,
        parent_order_id=parent_id,
        quantity=qty,
        cumulative_quantity=qty,
    )
    spot_remap.oco_group_id = None
    spot_remap.cumulative_value = Decimal("0")
    spot_remap.exchange_create_time = now
    spot_remap.exchange_update_time = now
    return trigger, spot_remap


def test_twin_fill_close_not_double_counted_long(db_session):
    """#523: dual-ID close rows must collapse, or a live long reads as 0."""
    entry = _bot_order(
        exchange_order_id="algo_buy_1",
        symbol="ALGO_USD",
        side=OrderSideEnum.BUY,
        quantity=Decimal("2000"),
        cumulative_quantity=Decimal("2000"),
    )
    trigger, spot_remap = _twin_close_pair(
        "ALGO_USD", "algo_buy_1", OrderSideEnum.SELL, Decimal("1149")
    )
    db_session.add_all([entry, trigger, spot_remap])
    db_session.commit()

    # Real close is 1149 of 2000 -> 851 still open (1 position). Counting both
    # twin rows sums 2298 > 2000, floors the net to 0 and hides a live position.
    assert count_open_positions_for_symbol(db_session, "ALGO_USD") == 1


def test_twin_fill_close_not_double_counted_short(db_session):
    """Same collapse on count_open_short_positions_for_symbol (its own query)."""
    short_entry = _bot_order(
        exchange_order_id="bonk_sell_1",
        symbol="BONK_USD",
        side=OrderSideEnum.SELL,
        quantity=Decimal("2000"),
        cumulative_quantity=Decimal("2000"),
    )
    trigger, spot_remap = _twin_close_pair(
        "BONK_USD", "bonk_sell_1", OrderSideEnum.BUY, Decimal("1149"), role="TAKE_PROFIT"
    )
    db_session.add_all([short_entry, trigger, spot_remap])
    db_session.commit()

    assert count_open_short_positions_for_symbol(db_session, "BONK_USD") == 1


def test_total_sums_bot_positions_across_symbols(db_session):
    db_session.add_all(
        [
            _bot_order(
                exchange_order_id="long_eth",
                symbol="ETH_USDT",
                side=OrderSideEnum.BUY,
                trade_signal_id=BOT_SIGNAL_ID,
            ),
            _bot_order(
                exchange_order_id="short_doge_1",
                symbol="DOGE_USD",
                side=OrderSideEnum.SELL,
                trade_signal_id=BOT_SIGNAL_ID + 1,
            ),
            _bot_order(
                exchange_order_id="short_doge_2",
                symbol="DOGE_USD",
                side=OrderSideEnum.SELL,
                trade_signal_id=BOT_SIGNAL_ID + 2,
            ),
            # Manual fill must not count
            _bot_order(
                exchange_order_id="manual_btc",
                symbol="BTC_USD",
                side=OrderSideEnum.BUY,
                trade_signal_id=None,
            ),
            # Orphan TP must not inflate total
            _bot_order(
                exchange_order_id="orphan_tp",
                symbol="BTC_USD",
                side=OrderSideEnum.SELL,
                status=OrderStatusEnum.ACTIVE,
                order_role="TAKE_PROFIT",
                trade_signal_id=None,
                parent_order_id="manual_btc",
            ),
        ]
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH") == 1
    assert count_open_positions_for_symbol(db_session, "DOGE") == 2
    assert count_total_open_positions(db_session) == 3
