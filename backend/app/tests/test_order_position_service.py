import pytest
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.order_position_service import count_open_positions_for_symbol


@pytest.fixture
def db_session():
  engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
  TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
  Base.metadata.create_all(bind=engine)

  session = TestingSessionLocal()
  try:
    yield session
  finally:
    session.close()
    Base.metadata.drop_all(bind=engine)
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
    trade_signal_id=None,
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
  )
  db_session.add_all([buy, sell])
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  assert count == 1


def test_multiple_buys_and_sells(db_session):
  """Multiple BUYs offset by multiple SELLs should count remaining open BUYs."""
  # BUY 1: fully closed
  buy1 = _make_order(
    exchange_order_id="buy_1",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("5"),
    cumulative_quantity=Decimal("5"),
  )
  # BUY 2: partially closed
  buy2 = _make_order(
    exchange_order_id="buy_2",
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("7"),
    cumulative_quantity=Decimal("7"),
  )
  # SELL 1: closes BUY 1 completely
  sell1 = _make_order(
    exchange_order_id="sell_1",
    side=OrderSideEnum.SELL,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("5"),
    cumulative_quantity=Decimal("5"),
    order_role=None,  # manual close
  )
  # SELL 2: partially closes BUY 2 (2/7)
  sell2 = _make_order(
    exchange_order_id="sell_2",
    side=OrderSideEnum.SELL,
    status=OrderStatusEnum.FILLED,
    quantity=Decimal("2"),
    cumulative_quantity=Decimal("2"),
    order_role="TAKE_PROFIT",
  )
  db_session.add_all([buy1, buy2, sell1, sell2])
  db_session.commit()

  count = count_open_positions_for_symbol(db_session, "ADA_USDT")
  # BUY1 is fully closed, BUY2 still has 5 units open => 1 open position
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
  # 1 pending + 1 filled (no SELL) => 2 open commitments
  assert count == 2


