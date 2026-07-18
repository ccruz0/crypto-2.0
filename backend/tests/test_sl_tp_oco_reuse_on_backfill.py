"""TP/SL backfill must reuse the surviving leg's oco_group_id."""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.exchange_sync import ExchangeSyncService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    for table in Base.metadata.tables.values():
        try:
            table.create(bind=engine, checkfirst=True)
        except OperationalError as e:
            if "already exists" not in str(e).lower():
                raise
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_tp_backfill_reuses_existing_sl_oco_group(db_session, monkeypatch):
    parent_id = "5755600491777401702"
    existing_oco = f"oco_{parent_id}_old"
    db_session.add(
        ExchangeOrder(
            exchange_order_id="73817490101973805",
            symbol="ETH_USDT",
            side=OrderSideEnum.BUY,
            order_type="STOP_LIMIT",
            status=OrderStatusEnum.ACTIVE,
            price=Decimal("2009.37"),
            quantity=Decimal("0.0054"),
            parent_order_id=parent_id,
            order_role="STOP_LOSS",
            oco_group_id=existing_oco,
            exchange_create_time=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    captured = {}

    def fake_tp(**kwargs):
        captured["oco_group_id"] = kwargs.get("oco_group_id")
        return {"order_id": "73817490102008105", "error": None}

    def should_not_create_sl(**_kwargs):
        raise AssertionError("SL already exists; create_stop_loss_order must not run")

    monkeypatch.setattr("app.services.tp_sl_order_creator.create_take_profit_order", fake_tp)
    monkeypatch.setattr("app.services.tp_sl_order_creator.create_stop_loss_order", should_not_create_sl)

    result = ExchangeSyncService()._create_sl_tp_impl(
        db=db_session,
        symbol="ETH_USDT",
        side_upper="SELL",
        filled_price_f=1826.7,
        filled_qty=0.0054,
        order_id=parent_id,
        source="test",
        strict_percentages=False,
        sl_price_override_f=None,
        tp_price_override_f=None,
    )

    assert result["sl_newly_created"] is False
    assert result["tp_newly_created"] is True
    assert result["oco_group_id"] == existing_oco
    assert captured["oco_group_id"] == existing_oco
    assert result["sl_result"]["order_id"] == "73817490101973805"
    assert result["tp_result"]["order_id"] == "73817490102008105"


def test_tp_backfill_heals_null_sl_oco_group(db_session, monkeypatch):
    parent_id = "5755600491778548045"
    db_session.add(
        ExchangeOrder(
            exchange_order_id="73817490101973900",
            symbol="ETH_USDT",
            side=OrderSideEnum.BUY,
            order_type="STOP_LIMIT",
            status=OrderStatusEnum.ACTIVE,
            price=Decimal("2033.11"),
            quantity=Decimal("0.0054"),
            parent_order_id=parent_id,
            order_role="STOP_LOSS",
            oco_group_id=None,
            exchange_create_time=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    def fake_tp(**kwargs):
        return {"order_id": "tp-new", "error": None}

    monkeypatch.setattr("app.services.tp_sl_order_creator.create_take_profit_order", fake_tp)
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_stop_loss_order",
        lambda **_k: (_ for _ in ()).throw(AssertionError("should reuse SL")),
    )

    result = ExchangeSyncService()._create_sl_tp_impl(
        db=db_session,
        symbol="ETH_USDT",
        side_upper="SELL",
        filled_price_f=1848.28,
        filled_qty=0.0054,
        order_id=parent_id,
        source="test",
        strict_percentages=False,
        sl_price_override_f=None,
        tp_price_override_f=None,
    )

    db_session.refresh(
        db_session.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == "73817490101973900").one()
    )
    sl = db_session.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == "73817490101973900").one()
    assert result["oco_group_id"]
    assert sl.oco_group_id == result["oco_group_id"]


@patch("app.services.telegram_notifier.TelegramNotifier.send_message", return_value=True)
def test_telegram_marks_reused_sl_on_tp_recreate(mock_send):
    from app.services.telegram_notifier import TelegramNotifier

    TelegramNotifier().send_sl_tp_orders(
        symbol="ETH_USDT",
        sl_price=2009.37,
        tp_price=1808.43,
        quantity=0.0054,
        mode="aggressive",
        sl_order_id="sl-old",
        tp_order_id="tp-new",
        original_order_id="parent-1",
        sl_side="BUY",
        tp_side="BUY",
        entry_price=1826.7,
        original_order_side="SELL",
        sl_newly_created=False,
        tp_newly_created=True,
    )
    message = mock_send.call_args[0][0]
    assert "TP ORDER RECREATED (SL reused)" in message
    assert "SL Order (exit) (reused)" in message
    assert "TP Order (exit)" in message
    assert "TP Order (exit) (reused)" not in message
