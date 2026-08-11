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

    details_usd = get_expected_take_profit_details(
        db_session,
        "BTC_USD",
        current_price=64000.0,
        portfolio_balance=float(wallet),
    )
    details_usdt = get_expected_take_profit_details(
        db_session,
        "BTC_USDT",
        current_price=64000.0,
        portfolio_balance=float(wallet),
    )
    # Details must use the same pair-share split as summary — never assign the
    # full base wallet to each sister book (BTC_USDT uncovered 1.59 regression).
    assert details_usd["net_qty"] + details_usdt["net_qty"] == pytest.approx(
        float(wallet), rel=1e-6
    )
    assert details_usd["net_qty"] <= float(wallet) + 1e-9
    assert details_usdt["net_qty"] <= float(wallet) + 1e-9
    assert details_usd["net_qty"] == pytest.approx(float(summary["BTC_USD"]["net_qty"]), rel=1e-6)
    if "BTC_USDT" in summary:
        assert details_usdt["net_qty"] == pytest.approx(
            float(summary["BTC_USDT"]["net_qty"]), rel=1e-6
        )
    else:
        assert details_usdt["net_qty"] == pytest.approx(0.0)
    assert details_usd.get("wallet_balance") == pytest.approx(float(wallet))
    assert details_usdt.get("wallet_balance") == pytest.approx(float(wallet))
    # USDT details must not invent uncovered ≈ full wallet minus a tiny covered lot.
    assert details_usdt["uncovered_qty"] <= details_usdt["net_qty"] + 1e-9
    assert details_usdt["uncovered_qty"] < 1.0


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


def test_details_sister_books_share_wallet_not_each_claim_full(db_session):
    """Prod BTC regression: USD+USDT details must not each use full wallet net_qty."""
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 1, tzinfo=timezone.utc)

    buy_usd = _add_order(
        db_session,
        exchange_order_id="btc-usd-main",
        symbol="BTC_USD",
        side=OrderSideEnum.BUY,
        price="60000",
        quantity="1.5",
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
        quantity="1.5",
        cumulative_quantity="0",
        parent_order_id=buy_usd.exchange_order_id,
        exchange_create_time=t0,
    )
    buy_usdt = _add_order(
        db_session,
        exchange_order_id="btc-usdt-main",
        symbol="BTC_USDT",
        side=OrderSideEnum.BUY,
        price="75000",
        quantity="0.4",
        exchange_create_time=t1,
    )
    _add_order(
        db_session,
        exchange_order_id="btc-usdt-tp",
        symbol="BTC_USDT",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="80000",
        quantity="0.4",
        cumulative_quantity="0",
        parent_order_id=buy_usdt.exchange_order_id,
        exchange_create_time=t1,
    )

    wallet = 1.9
    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[{"coin": "BTC", "balance": wallet, "value_usd": 120000.0}],
        market_prices={"BTC": 64000.0, "BTC_USD": 64000.0, "BTC_USDT": 64000.0},
    )
    details_usd = get_expected_take_profit_details(
        db_session, "BTC_USD", current_price=64000.0, portfolio_balance=wallet
    )
    details_usdt = get_expected_take_profit_details(
        db_session, "BTC_USDT", current_price=64000.0, portfolio_balance=wallet
    )

    assert "BTC_USD" in summary and "BTC_USDT" in summary
    assert details_usd["net_qty"] + details_usdt["net_qty"] == pytest.approx(wallet, rel=1e-6)
    assert details_usd["net_qty"] == pytest.approx(float(summary["BTC_USD"]["net_qty"]), rel=1e-6)
    assert details_usdt["net_qty"] == pytest.approx(float(summary["BTC_USDT"]["net_qty"]), rel=1e-6)
    # Neither modal may claim the full wallet alone when both books have inventory.
    assert details_usd["net_qty"] < wallet
    assert details_usdt["net_qty"] < wallet
    assert details_usdt["uncovered_qty"] < 1.0


def test_same_side_sister_trim_keeps_protected_btc_usd_details(db_session):
    """Executed Orders → Expected TP must show BTC_USD SL/TP when wallet is dust.

    Oldest-first same-side trim used to keep a large older BTC_USDT lot and drop
    the newer protected BTC_USD fill, so details returned empty entry_orders
    ("No matched lots found") even though USD SL/TP were ACTIVE.
    """
    t_usdt = datetime(2026, 7, 1, tzinfo=timezone.utc)
    t_usd = datetime(2026, 8, 7, 4, 2, tzinfo=timezone.utc)

    buy_usdt = _add_order(
        db_session,
        exchange_order_id="btc-usdt-old-1.5",
        symbol="BTC_USDT",
        side=OrderSideEnum.BUY,
        price="65000",
        quantity="1.5",
        exchange_create_time=t_usdt,
    )
    _add_order(
        db_session,
        exchange_order_id="btc-usdt-old-tp",
        symbol="BTC_USDT",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="70000",
        quantity="1.5",
        cumulative_quantity="0",
        parent_order_id=buy_usdt.exchange_order_id,
        exchange_create_time=t_usdt,
    )

    buy_usd = _add_order(
        db_session,
        exchange_order_id="5755600492731962293",
        symbol="BTC_USD",
        side=OrderSideEnum.BUY,
        price="64206.97",
        quantity="0.000150",
        exchange_create_time=t_usd,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490102062566",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="64849.04",
        quantity="0.000150",
        cumulative_quantity="0",
        parent_order_id=buy_usd.exchange_order_id,
        exchange_create_time=t_usd,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490102062567",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        order_type="STOP_LOSS_LIMIT",
        order_role="STOP_LOSS",
        status=OrderStatusEnum.ACTIVE,
        price="57786.27",
        quantity="0.000150",
        cumulative_quantity="0",
        parent_order_id=buy_usd.exchange_order_id,
        exchange_create_time=t_usd,
    )

    wallet = 0.000150
    details = get_expected_take_profit_details(
        db_session,
        "BTC_USD",
        current_price=64128.85,
        portfolio_balance=wallet,
    )

    assert details["entry_orders"], "BTC_USD details must not be empty when fill is protected"
    by_id = {entry["order_id"]: entry for entry in details["entry_orders"]}
    assert buy_usd.exchange_order_id in by_id
    usd_row = by_id[buy_usd.exchange_order_id]
    assert any(tp["order_id"] == "73817490102062566" for tp in usd_row["take_profits"])
    assert usd_row["stop_loss"] is not None
    assert usd_row["stop_loss"]["order_id"] == "73817490102062567"
    assert details.get("wallet_qty_warning") == "lots_exceed_wallet"


def test_same_side_unprotected_usdt_does_not_hide_protected_usd(db_session):
    """Unprotected oversized USDT lot must yield wallet capacity to protected USD."""
    t_usdt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t_usd = datetime(2026, 8, 7, 4, 42, tzinfo=timezone.utc)

    _add_order(
        db_session,
        exchange_order_id="btc-usdt-unprotected",
        symbol="BTC_USDT",
        side=OrderSideEnum.BUY,
        price="64000",
        quantity="1.5",
        exchange_create_time=t_usdt,
    )
    buy_usd = _add_order(
        db_session,
        exchange_order_id="btc-usd-protected-dust",
        symbol="BTC_USD",
        side=OrderSideEnum.BUY,
        price="64200",
        quantity="0.000150",
        exchange_create_time=t_usd,
    )
    _add_order(
        db_session,
        exchange_order_id="btc-usd-dust-tp",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="64800",
        quantity="0.000150",
        cumulative_quantity="0",
        parent_order_id=buy_usd.exchange_order_id,
        exchange_create_time=t_usd,
    )
    _add_order(
        db_session,
        exchange_order_id="btc-usd-dust-sl",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        order_type="STOP_LOSS_LIMIT",
        order_role="STOP_LOSS",
        status=OrderStatusEnum.ACTIVE,
        price="58000",
        quantity="0.000150",
        cumulative_quantity="0",
        parent_order_id=buy_usd.exchange_order_id,
        exchange_create_time=t_usd,
    )

    wallet = 0.000150
    details = get_expected_take_profit_details(
        db_session,
        "BTC_USD",
        current_price=64100.0,
        portfolio_balance=wallet,
    )
    entry_ids = {entry["order_id"] for entry in details["entry_orders"]}
    assert buy_usd.exchange_order_id in entry_ids
    # Protected USD should claim the wallet; unprotected USDT is trimmed away.
    assert details["net_qty"] == pytest.approx(wallet, rel=1e-6)
    usd_row = next(e for e in details["entry_orders"] if e["order_id"] == buy_usd.exchange_order_id)
    assert usd_row["stop_loss"] is not None
    assert usd_row["take_profits"]


def test_naked_micro_short_visible_when_protected_covers_wallet(db_session):
    """ETH-like: protected shorts cover |wallet|; naked micro with failed SL/TP stays visible."""
    t_prot = datetime(2026, 8, 4, tzinfo=timezone.utc)
    t_naked = datetime(2026, 8, 5, 17, 54, tzinfo=timezone.utc)

    protected = _add_order(
        db_session,
        exchange_order_id="eth-protected-short",
        symbol="ETH_USDT",
        side=OrderSideEnum.SELL,
        price="1900",
        quantity="0.124",
        exchange_create_time=t_prot,
    )
    _add_order(
        db_session,
        exchange_order_id="eth-protected-tp",
        symbol="ETH_USDT",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="1800",
        quantity="0.124",
        cumulative_quantity="0",
        parent_order_id=protected.exchange_order_id,
        exchange_create_time=t_prot,
    )
    _add_order(
        db_session,
        exchange_order_id="eth-protected-sl",
        symbol="ETH_USDT",
        side=OrderSideEnum.BUY,
        order_type="STOP_LOSS_LIMIT",
        order_role="STOP_LOSS",
        status=OrderStatusEnum.ACTIVE,
        price="2100",
        quantity="0.124",
        cumulative_quantity="0",
        parent_order_id=protected.exchange_order_id,
        exchange_create_time=t_prot,
    )
    naked = _add_order(
        db_session,
        exchange_order_id="5755600492671134850",
        symbol="ETH_USDT",
        side=OrderSideEnum.SELL,
        price="1914.8",
        quantity="0.0052",
        exchange_create_time=t_naked,
    )

    wallet = -0.124
    details = get_expected_take_profit_details(
        db_session,
        "ETH_USDT",
        current_price=1900.0,
        portfolio_balance=wallet,
    )
    entry_ids = {entry["order_id"] for entry in details["entry_orders"]}
    assert protected.exchange_order_id in entry_ids
    assert naked.exchange_order_id in entry_ids, (
        "Naked micro with missing SL/TP must stay visible in Expected TP"
    )
    naked_row = next(e for e in details["entry_orders"] if e["order_id"] == naked.exchange_order_id)
    assert naked_row["take_profits"] == []
    assert naked_row["stop_loss"] is None
    # Wallet truth stays the exchange balance (not inflated by the pinned micro).
    assert details["net_qty"] == pytest.approx(abs(wallet), rel=1e-6)
    assert details.get("wallet_qty_warning") == "lots_exceed_wallet"
