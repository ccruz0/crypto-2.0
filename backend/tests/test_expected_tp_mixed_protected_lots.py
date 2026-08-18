"""Protected MIXED long+short lots must both surface in Expected TP details.

ALGO_USD regression: short wallet residue trimmed away the protected LONG entry,
so Executed Orders deep-link / symbol details showed only the old SHORT lot.
"""

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
    qty = kwargs.get("quantity", "1")
    order = ExchangeOrder(
        exchange_order_id=kwargs["exchange_order_id"],
        symbol=kwargs.get("symbol", "ALGO_USD"),
        side=kwargs.get("side", OrderSideEnum.BUY),
        order_type=kwargs.get("order_type", "LIMIT"),
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        order_role=kwargs.get("order_role"),
        parent_order_id=kwargs.get("parent_order_id"),
        price=Decimal(str(kwargs.get("price", "0.1"))),
        quantity=Decimal(str(qty)),
        cumulative_quantity=Decimal(str(kwargs.get("cumulative_quantity", qty))),
        cumulative_value=Decimal(str(kwargs.get("cumulative_value", "0"))),
        avg_price=Decimal(str(kwargs.get("price", "0.1"))),
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(order)
    db_session.commit()
    return order


def test_algo_short_wallet_keeps_protected_long_and_short_lots(db_session):
    """Short wallet must not hide today's protected ALGO BUY behind the old SHORT."""
    t_short = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    t_long = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

    short_entry = _add_order(
        db_session,
        exchange_order_id="5755600486727374988",
        symbol="ALGO_USD",
        side=OrderSideEnum.SELL,
        price="0.10475",
        quantity="14.23318617",
        exchange_create_time=t_short,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490102052002",
        symbol="ALGO_USD",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="0.08",
        quantity="14.23318617",
        cumulative_quantity="0",
        parent_order_id=short_entry.exchange_order_id,
        exchange_create_time=t_short,
    )

    long_entry = _add_order(
        db_session,
        exchange_order_id="5755600492696996146",
        symbol="ALGO_USD",
        side=OrderSideEnum.BUY,
        price="0.09",
        quantity="114",
        exchange_create_time=t_long,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490102060693",
        symbol="ALGO_USD",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="0.12",
        quantity="114",
        cumulative_quantity="0",
        parent_order_id=long_entry.exchange_order_id,
        exchange_create_time=t_long,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490102060694",
        symbol="ALGO_USD",
        side=OrderSideEnum.SELL,
        order_type="STOP_LOSS_LIMIT",
        order_role="STOP_LOSS",
        status=OrderStatusEnum.ACTIVE,
        price="0.07",
        quantity="114",
        cumulative_quantity="0",
        parent_order_id=long_entry.exchange_order_id,
        exchange_create_time=t_long,
    )

    wallet = -14.23318617
    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[{"coin": "ALGO", "balance": wallet, "value_usd": -1.24}],
        market_prices={"ALGO": 0.087, "ALGO_USD": 0.087},
    )

    algo = summary.get("ALGO_USD")
    assert algo is not None
    assert algo["net_qty"] == pytest.approx(abs(wallet))
    assert algo["position_side"] == "MIXED"
    assert algo["entry_lot_count"] == 2
    assert algo.get("wallet_qty_warning") == "lots_exceed_wallet"

    details = get_expected_take_profit_details(
        db_session,
        "ALGO_USD",
        current_price=0.087,
        portfolio_balance=wallet,
    )
    assert details["position_side"] == "MIXED"
    assert details["net_qty"] == pytest.approx(abs(wallet))

    by_id = {entry["order_id"]: entry for entry in details["entry_orders"]}
    assert long_entry.exchange_order_id in by_id
    assert short_entry.exchange_order_id in by_id

    long_row = by_id[long_entry.exchange_order_id]
    assert long_row["side"] == "BUY"
    assert long_row["qty"] == pytest.approx(114.0)
    assert any(tp["order_id"] == "73817490102060693" for tp in long_row["take_profits"])
    assert long_row["stop_loss"] is not None
    assert long_row["stop_loss"]["order_id"] == "73817490102060694"

    short_row = by_id[short_entry.exchange_order_id]
    assert short_row["side"] == "SELL"
    assert any(tp["order_id"] == "73817490102052002" for tp in short_row["take_profits"])


def test_eth_negative_wallet_keeps_protected_long_in_details(db_session):
    """Negative ETH wallet must still list the protected BUY long entry order."""
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

    wallet = -0.0302
    details = get_expected_take_profit_details(
        db_session,
        "ETH_USD",
        current_price=1872.0,
        portfolio_balance=wallet,
    )
    assert details["net_qty"] == pytest.approx(abs(wallet))
    assert details["position_side"] == "MIXED"
    entry_ids = {entry["order_id"] for entry in details["entry_orders"]}
    assert buy_long.exchange_order_id in entry_ids
    assert sell_a.exchange_order_id in entry_ids
    assert sell_b.exchange_order_id in entry_ids


def test_positive_wallet_mixed_trim_surfaces_ghost_mixed_trimmed(db_session):
    """The trim warning must reach the summary row, not be replaced downstream.

    #497 added ghost_mixed_trimmed but _align_open_lots_to_wallet only used it to
    decide whether to bail out — every return path then rebuilt the warning from
    scratch as lots_exceed_wallet or None, so the value never left the function
    and the badge #497 promised could not render.
    """
    t_short = datetime(2026, 4, 1, 14, 54, tzinfo=timezone.utc)
    t_long = datetime(2026, 8, 7, 17, 40, tzinfo=timezone.utc)

    # Unmatchable SELL with no live protection: the phantom short #496 describes.
    _add_order(
        db_session,
        exchange_order_id="5755600486727374908",
        symbol="ALGO_USD",
        side=OrderSideEnum.SELL,
        price="0.10483",
        quantity="1796",
        exchange_create_time=t_short,
    )

    long_entry = _add_order(
        db_session,
        exchange_order_id="5755600492696996146",
        symbol="ALGO_USD",
        side=OrderSideEnum.BUY,
        price="0.08829",
        quantity="1132",
        exchange_create_time=t_long,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490102060693",
        symbol="ALGO_USD",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="0.095",
        quantity="1132",
        cumulative_quantity="0",
        parent_order_id=long_entry.exchange_order_id,
        exchange_create_time=t_long,
    )

    wallet = 1132.0
    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[{"coin": "ALGO", "balance": wallet, "value_usd": 99.9}],
        market_prices={"ALGO": 0.0883, "ALGO_USD": 0.0883},
    )

    algo = summary.get("ALGO_USD")
    assert algo is not None, "positive wallet must keep the legitimate long visible"
    assert algo.get("wallet_qty_warning") == "ghost_mixed_trimmed"
    # The long survives; only the phantom short is gone.
    assert algo["position_side"] == "LONG"
    assert algo["net_qty"] == pytest.approx(wallet)


def test_details_does_not_clobber_mixed_trim_when_trim_leaves_only_shorts(db_session):
    """Summary and details must not disagree on the same symbol.

    The details path re-derives the warning from `resolve_position_side`, but by
    then `open_lots` has been REASSIGNED to the post-alignment list (see the
    `open_lots, pair_share = allocated[symbol]` line). If the wallet trim drops
    oversized unprotected longs and leaves only protected shorts, that list is
    pure SHORT against a positive wallet, and the check overwrites a surviving
    ghost_mixed_trimmed with ghost_short_vs_long.

    Found by Cursor Bugbot on PR #505.
    """
    t_prot = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    t_naked = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
    t_long = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)

    # Protected short, sized to eat the whole wallet so nothing else fits.
    protected_short = _add_order(
        db_session,
        exchange_order_id="algo-short-protected",
        symbol="ALGO_USD",
        side=OrderSideEnum.SELL,
        price="0.10",
        quantity="10",
        exchange_create_time=t_prot,
    )
    _add_order(
        db_session,
        exchange_order_id="algo-short-protected-tp",
        symbol="ALGO_USD",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="0.09",
        quantity="10",
        cumulative_quantity="0",
        parent_order_id=protected_short.exchange_order_id,
        exchange_create_time=t_prot,
    )
    # Unprotected short: the ghost the filter drops -> ghost_mixed_trimmed.
    _add_order(
        db_session,
        exchange_order_id="algo-short-naked",
        symbol="ALGO_USD",
        side=OrderSideEnum.SELL,
        price="0.10",
        quantity="5",
        exchange_create_time=t_naked,
    )
    # Oversized unprotected long: survives the ghost filter, then the wallet
    # trim drops it because the protected short already fills |wallet|.
    _add_order(
        db_session,
        exchange_order_id="algo-long-oversized",
        symbol="ALGO_USD",
        side=OrderSideEnum.BUY,
        price="0.09",
        quantity="50",
        exchange_create_time=t_long,
    )

    wallet = 10.0
    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[{"coin": "ALGO", "balance": wallet, "value_usd": 0.9}],
        market_prices={"ALGO": 0.09, "ALGO_USD": 0.09},
    )
    algo = summary.get("ALGO_USD")
    assert algo is not None
    assert algo.get("wallet_qty_warning") == "ghost_mixed_trimmed"

    details = get_expected_take_profit_details(
        db_session, "ALGO_USD", current_price=0.09, portfolio_balance=wallet
    )
    assert details.get("wallet_qty_warning") == algo.get("wallet_qty_warning"), (
        "details must not re-derive a different warning than summary"
    )
