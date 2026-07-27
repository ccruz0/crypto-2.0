"""Short / dual-path SL+TP: avoid INSUFFICIENT_ACC_BALANCE when SL locks qty first."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.exchange_sync import ExchangeSyncService
from app.services.tp_sl_order_creator import is_insufficient_acc_balance_error


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


def test_is_insufficient_acc_balance_error():
    assert is_insufficient_acc_balance_error("INSUFFICIENT_ACC_BALANCE")
    assert is_insufficient_acc_balance_error("code=306 INSUFFICIENT_AVAILABLE_BALANCE")
    assert not is_insufficient_acc_balance_error("INVALID_PRICE")
    assert not is_insufficient_acc_balance_error(None)


def test_margin_short_dual_places_tp_before_sl(db_session, monkeypatch):
    """New short (margin, both legs missing): TP first then SL."""
    monkeypatch.setenv("SLTP_NATIVE_OCO", "true")
    order: list[str] = []

    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_oco_protection_orders",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("margin must skip OCO")),
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
        lambda db, symbol: (True, 5.0),
    )
    monkeypatch.setattr(
        "app.services.exchange_sync.get_active_protection_order",
        lambda db, parent, role: None,
    )

    def _tp(**kwargs):
        order.append("tp")
        assert kwargs["side"] == "SELL"
        return {"order_id": "tp-short-1", "error": None}

    def _sl(**kwargs):
        order.append("sl")
        assert kwargs["side"] == "SELL"
        return {"order_id": "sl-short-1", "error": None}

    monkeypatch.setattr("app.services.tp_sl_order_creator.create_take_profit_order", _tp)
    monkeypatch.setattr("app.services.tp_sl_order_creator.create_stop_loss_order", _sl)

    result = ExchangeSyncService()._create_sl_tp_impl(
        db=db_session,
        symbol="ETH_USDT",
        side_upper="SELL",
        filled_price_f=2000.0,
        filled_qty=0.05,
        order_id="short-parent-1",
        source="test",
        strict_percentages=False,
        sl_price_override_f=2060.0,
        tp_price_override_f=1940.0,
    )

    assert order == ["tp", "sl"]
    assert result["tp_result"]["order_id"] == "tp-short-1"
    assert result["sl_result"]["order_id"] == "sl-short-1"
    assert result["sl_price"] == 2060.0
    assert result["tp_price"] == 1940.0


def test_existing_sl_insufficient_tp_cancels_then_tp_then_sl(db_session, monkeypatch):
    """Backfill TP while SL locks qty → cancel SL, place TP, recreate SL."""
    monkeypatch.setenv("SLTP_NATIVE_OCO", "false")
    parent_id = "short-parent-locked"
    existing_sl = ExchangeOrder(
        exchange_order_id="sl-live-1",
        symbol="ETH_USDT",
        side=OrderSideEnum.BUY,
        order_type="STOP_LIMIT",
        status=OrderStatusEnum.ACTIVE,
        price=Decimal("2060"),
        quantity=Decimal("0.05"),
        parent_order_id=parent_id,
        order_role="STOP_LOSS",
        oco_group_id=f"oco_{parent_id}_1",
        exchange_create_time=datetime.now(timezone.utc),
    )
    db_session.add(existing_sl)
    db_session.commit()

    calls: list[str] = []
    tp_attempts = {"n": 0}

    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
        lambda db, symbol: (True, 5.0),
    )

    def _get_active(db, parent, role):
        if role == "STOP_LOSS":
            row = (
                db.query(ExchangeOrder)
                .filter(
                    ExchangeOrder.parent_order_id == parent,
                    ExchangeOrder.order_role == "STOP_LOSS",
                    ExchangeOrder.status.in_(
                        [
                            OrderStatusEnum.NEW,
                            OrderStatusEnum.ACTIVE,
                            OrderStatusEnum.PARTIALLY_FILLED,
                        ]
                    ),
                )
                .first()
            )
            return row
        return None

    monkeypatch.setattr("app.services.exchange_sync.get_active_protection_order", _get_active)

    def _tp(**kwargs):
        tp_attempts["n"] += 1
        calls.append(f"tp{tp_attempts['n']}")
        if tp_attempts["n"] == 1:
            return {"order_id": None, "error": "INSUFFICIENT_ACC_BALANCE"}
        return {"order_id": "tp-recovered", "error": None}

    def _sl(**kwargs):
        calls.append("sl")
        return {"order_id": "sl-recovered", "error": None}

    monkeypatch.setattr("app.services.tp_sl_order_creator.create_take_profit_order", _tp)
    monkeypatch.setattr("app.services.tp_sl_order_creator.create_stop_loss_order", _sl)

    cancel_calls = []

    class _FakeClient:
        def cancel_order(self, order_id, order_type=None, **kwargs):
            cancel_calls.append((order_id, order_type))
            return {"order_id": order_id, "status": "CANCELLED"}

    monkeypatch.setattr(
        "app.services.exchange_sync.trade_client",
        _FakeClient(),
    )

    result = ExchangeSyncService()._create_sl_tp_impl(
        db=db_session,
        symbol="ETH_USDT",
        side_upper="SELL",
        filled_price_f=2000.0,
        filled_qty=0.05,
        order_id=parent_id,
        source="test",
        strict_percentages=False,
        sl_price_override_f=2060.0,
        tp_price_override_f=1940.0,
    )

    assert cancel_calls and cancel_calls[0][0] == "sl-live-1"
    assert calls == ["tp1", "tp2", "sl"]
    assert result["tp_result"]["order_id"] == "tp-recovered"
    assert result["sl_result"]["order_id"] == "sl-recovered"
    db_session.refresh(existing_sl)
    assert existing_sl.status == OrderStatusEnum.CANCELLED


def test_spot_native_oco_still_preferred(db_session, monkeypatch):
    monkeypatch.setenv("SLTP_NATIVE_OCO", "true")
    oco_calls = []
    legacy = []

    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
        lambda db, symbol: (False, None),
    )
    monkeypatch.setattr(
        "app.services.exchange_sync.get_active_protection_order",
        lambda db, parent, role: None,
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_oco_protection_orders",
        lambda **kwargs: oco_calls.append(kwargs)
        or {
            "sl_result": {"order_id": "sl-oco", "error": None},
            "tp_result": {"order_id": "tp-oco", "error": None},
            "oco_group_id": "6498090546073120999",
            "error": None,
            "sl_newly_created": True,
            "tp_newly_created": True,
        },
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_stop_loss_order",
        lambda **kwargs: legacy.append("sl") or {"order_id": "x"},
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_take_profit_order",
        lambda **kwargs: legacy.append("tp") or {"order_id": "y"},
    )

    result = ExchangeSyncService()._create_sl_tp_impl(
        db=db_session,
        symbol="ETH_USDT",
        side_upper="BUY",
        filled_price_f=2000.0,
        filled_qty=0.01,
        order_id="spot-parent",
        source="test",
        strict_percentages=False,
        sl_price_override_f=1900.0,
        tp_price_override_f=2100.0,
    )
    assert len(oco_calls) == 1
    assert not legacy
    assert result["oco_group_id"] == "6498090546073120999"
