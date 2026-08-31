"""End-to-end regression for issue #496 (ALGO phantom short / BUY cover bleed).

FIFO still materialises unmatched SELL remainder as SELL-entry lots internally,
but wallet alignment must drop phantom shorts on positive balances, Expected TP
must not report them as open SHORT inventory, and every SL/TP creation path must
refuse BUY-side cover when the base wallet is not negative.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import (
    _align_open_lots_to_wallet,
    _entry_side_for_lot,
    get_expected_take_profit_summary,
    rebuild_open_lots,
)
from app.services.sl_tp_checker import _iter_naked_entry_parents
from app.services.tp_sl_order_creator import create_take_profit_order


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
        cumulative_value=Decimal(str(kwargs.get("cumulative_value", "100"))),
        avg_price=Decimal(str(kwargs.get("price", "0.1"))),
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(order)
    db_session.commit()
    return order


def _seed_algo_mixed_phantom_short(db_session):
    """ALGO-shaped book: orphan Apr SELL + Aug long with live SELL TP."""
    t_orphan = datetime(2026, 4, 1, 14, 54, tzinfo=timezone.utc)
    t_long = datetime(2026, 8, 7, 17, 40, tzinfo=timezone.utc)

    orphan_sell = _add_order(
        db_session,
        exchange_order_id="5755600486727374908",
        side=OrderSideEnum.SELL,
        price="0.10483",
        quantity="1796",
        exchange_create_time=t_orphan,
    )
    long_entry = _add_order(
        db_session,
        exchange_order_id="5755600492696996146",
        side=OrderSideEnum.BUY,
        price="0.08829",
        quantity="1132",
        exchange_create_time=t_long,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490102060693",
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
    return orphan_sell, long_entry


def test_fifo_builds_phantom_short_lot_before_wallet_align(db_session):
    """Raw FIFO still sees the orphan SELL — alignment is what removes it."""
    orphan_sell, _ = _seed_algo_mixed_phantom_short(db_session)

    raw_lots = rebuild_open_lots(db_session, "ALGO")
    sides = {_entry_side_for_lot(db_session, lot) for lot in raw_lots}
    assert OrderSideEnum.SELL in sides
    assert OrderSideEnum.BUY in sides
    orphan_ids = {
        lot.buy_order_id
        for lot in raw_lots
        if _entry_side_for_lot(db_session, lot) == OrderSideEnum.SELL
    }
    assert orphan_sell.exchange_order_id in orphan_ids


def test_wallet_align_drops_phantom_short_keeps_long(db_session):
    orphan_sell, long_entry = _seed_algo_mixed_phantom_short(db_session)
    wallet = Decimal("1132")

    aligned, warning = _align_open_lots_to_wallet(
        db_session, rebuild_open_lots(db_session, "ALGO"), wallet
    )
    assert warning == "ghost_mixed_trimmed"
    assert len(aligned) == 1
    assert aligned[0].buy_order_id == long_entry.exchange_order_id
    assert orphan_sell.exchange_order_id not in {lot.buy_order_id for lot in aligned}


def test_expected_tp_summary_long_only_after_mixed_trim(db_session):
    _seed_algo_mixed_phantom_short(db_session)
    wallet = 1132.0

    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[{"coin": "ALGO", "balance": wallet, "value_usd": 99.9}],
        market_prices={"ALGO": 0.0883, "ALGO_USD": 0.0883},
    )
    algo = summary.get("ALGO_USD")
    assert algo is not None
    assert algo["position_side"] == "LONG"
    assert algo["net_qty"] == pytest.approx(wallet)
    assert algo.get("wallet_qty_warning") == "ghost_mixed_trimmed"


@patch("app.services.tp_sl_order_creator.trade_client")
@patch(
    "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
    return_value=(False, None),
)
def test_buy_tp_blocked_for_phantom_short_entry(
    _margin_ctx, mock_client, db_session
):
    """Creation choke point must refuse BUY cover when wallet is not negative."""
    orphan_sell, _ = _seed_algo_mixed_phantom_short(db_session)
    mock_client.get_account_summary.return_value = {
        "accounts": [{"currency": "ALGO", "balance": 1220.1149}]
    }

    result = create_take_profit_order(
        db=db_session,
        symbol="ALGO_USD",
        side="SELL",
        tp_price=0.0799,
        quantity=1796.0,
        entry_price=0.10483,
        parent_order_id=orphan_sell.exchange_order_id,
    )

    assert result.get("order_id") is None
    assert "no short to cover" in (result.get("error") or "")
    mock_client.create_order.assert_not_called()


def test_naked_parent_scan_skips_phantom_sell_on_long_wallet(db_session):
    """Positive wallet uses entry_side=BUY — orphan SELL must not surface as naked."""
    orphan_sell, long_entry = _seed_algo_mixed_phantom_short(db_session)

    naked = _iter_naked_entry_parents(
        db_session, "ALGO_USD", entry_side="BUY", lookback_hours=0
    )
    naked_ids = {p.exchange_order_id for p in naked}
    assert orphan_sell.exchange_order_id not in naked_ids
    assert long_entry.exchange_order_id in naked_ids
