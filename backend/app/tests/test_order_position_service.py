import pytest
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.order_position_service import count_open_positions_for_symbol

BOT_SIGNAL_ID = 1001


@pytest.fixture
def db_session():
  engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
  TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
  Base.metadata.create_all(bind=engine, tables=[ExchangeOrder.__table__])

  session = TestingSessionLocal()
  try:
    yield session
  finally:
    session.close()
    Base.metadata.drop_all(bind=engine, tables=[ExchangeOrder.__table__])
    engine.dispose()


def _make_order(**kwargs) -> ExchangeOrder:
  now = datetime.now(timezone.utc)
  defaults = dict(
    exchange_order_id=kwargs.get("exchange_order_id", f"ord_{now.timestamp()}"),
    client_oid=kwargs.get("client_oid", None),
    symbol=kwargs.get("symbol", "ADA_USDT"),
    side=kwargs.get("side", OrderSideEnum.BUY),
    order_type=kwargs.get("order_type", "MARKET"),
    status=kwargs.get("status", OrderStatusEnum.NEW),
    price=kwargs.get("price", Decimal("1.0")),
    quantity=kwargs.get("quantity", Decimal("1.0")),
    cumulative_quantity=kwargs.get("cumulative_quantity", Decimal("1.0")),
    cumulative_value=kwargs.get("cumulative_value", Decimal("1.0")),
    avg_price=kwargs.get("avg_price", Decimal("1.0")),
    trigger_condition=None,
    exchange_create_time=now,
    exchange_update_time=now,
    created_at=now,
    updated_at=now,
    imported_at=None,
    trade_signal_id=kwargs.get("trade_signal_id", BOT_SIGNAL_ID),
    parent_order_id=kwargs.get("parent_order_id", None),
    oco_group_id=kwargs.get("oco_group_id", None),
    order_role=kwargs.get("order_role", None),
  )
  return ExchangeOrder(**defaults)


def test_full_buy_no_sell_counts_one(db_session):
  """Full BUY with no SELL should count as 1 open position."""
  buy = _make_order(
    exchange_order_id="buy_1",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("10"),
    cumulative_quantity=Decimal("10"),
  )
  db_session.add(buy)
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 1


def test_buy_fully_closed_by_sell_counts_zero(db_session):
  """BUY fully closed by SELL should result in 0 open positions."""
  buy = _make_order(
    exchange_order_id="buy_1",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("10"),
    cumulative_quantity=Decimal("10"),
  )
  sell = _make_order(
    exchange_order_id="sell_1",
    side=OrderSideEnum.SELL,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("10"),
    cumulative_quantity=Decimal("10"),
    order_role="TAKE_PROFIT",
    trade_signal_id=None,
  )
  db_session.add_all([buy, sell])
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 0


def test_partial_sell_still_counts_one(db_session):
  """Partial SELL should still leave the BUY as one open position."""
  buy = _make_order(
    exchange_order_id="buy_1",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("10"),
    cumulative_quantity=Decimal("10"),
  )
  sell = _make_order(
    exchange_order_id="sell_1",
    side=OrderSideEnum.SELL,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("5"),
    cumulative_quantity=Decimal("5"),
    order_role="STOP_LOSS",
    trade_signal_id=None,
  )
  db_session.add_all([buy, sell])
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 1


def test_multiple_buys_and_sells(db_session):
  """Multiple BUYs offset by multiple SELLs should count remaining open BUYs."""
  buy1 = _make_order(
    exchange_order_id="buy_1",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("5"),
    cumulative_quantity=Decimal("5"),
  )
  buy2 = _make_order(
    exchange_order_id="buy_2",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("7"),
    cumulative_quantity=Decimal("7"),
  )
  sell1 = _make_order(
    exchange_order_id="sell_1",
    side=OrderSideEnum.SELL,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("5"),
    cumulative_quantity=Decimal("5"),
    parent_order_id="buy_1",
    trade_signal_id=None,
  )
  sell2 = _make_order(
    exchange_order_id="sell_2",
    side=OrderSideEnum.SELL,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("2"),
    cumulative_quantity=Decimal("2"),
    order_role="TAKE_PROFIT",
    trade_signal_id=None,
  )
  db_session.add_all([buy1, buy2, sell1, sell2])
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 1


def test_pending_and_filled_buy_counts_more_than_one(db_session):
  """Pending BUY + filled BUY (still open) should count as >1."""
  pending_buy = _make_order(
    exchange_order_id="buy_pending",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.NEW,
    quantity=Decimal("3"),
    cumulative_quantity=Decimal("0"),
  )
  filled_buy = _make_order(
    exchange_order_id="buy_filled",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("4"),
    cumulative_quantity=Decimal("4"),
  )
  db_session.add_all([pending_buy, filled_buy])
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 2


def test_filled_short_entry_counts_one(db_session):
  """One filled bot SELL entry (short) with no cover BUY counts as 1."""
  short_entry = _make_order(
    exchange_order_id="short_1",
    side=OrderSideEnum.SELL,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("2"),
    cumulative_quantity=Decimal("2"),
  )
  db_session.add(short_entry)
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 1


def test_three_short_entries_count_three(db_session):
  """Three filled short entries should count 3 — per-coin guard would block a 2nd."""
  for i in range(3):
    db_session.add(
      _make_order(
        exchange_order_id=f"short_{i}",
        side=OrderSideEnum.SELL,
        status=OrderStatusEnum.FILLED,
        quantity=Decimal("1"),
        cumulative_quantity=Decimal("1"),
        trade_signal_id=BOT_SIGNAL_ID + i,
      )
    )
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 3


def test_short_protection_sell_does_not_count_as_position(db_session):
  """STOP_LOSS / parent-linked SELL must not count as an open short position."""
  protection = _make_order(
    exchange_order_id="sl_1",
    side=OrderSideEnum.SELL,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("1"),
    cumulative_quantity=Decimal("1"),
    order_role="STOP_LOSS",
    trade_signal_id=None,
    parent_order_id="parent_buy",
  )
  db_session.add(protection)
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 0


def test_short_closed_by_protection_buy_counts_zero(db_session):
  """Short entry fully covered by protection BUY should count 0."""
  short_entry = _make_order(
    exchange_order_id="short_1",
    side=OrderSideEnum.SELL,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("5"),
    cumulative_quantity=Decimal("5"),
  )
  cover = _make_order(
    exchange_order_id="cover_1",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("5"),
    cumulative_quantity=Decimal("5"),
    order_role="TAKE_PROFIT",
    trade_signal_id=None,
    parent_order_id="short_1",
  )
  db_session.add_all([short_entry, cover])
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 0


def test_short_entry_does_not_offset_long(db_session):
  """Short-entry SELL must not reduce the open long count."""
  buy = _make_order(
    exchange_order_id="buy_1",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("10"),
    cumulative_quantity=Decimal("10"),
  )
  short_entry = _make_order(
    exchange_order_id="short_1",
    side=OrderSideEnum.SELL,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("3"),
    cumulative_quantity=Decimal("3"),
    trade_signal_id=BOT_SIGNAL_ID + 1,
  )
  db_session.add_all([buy, short_entry])
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 2
