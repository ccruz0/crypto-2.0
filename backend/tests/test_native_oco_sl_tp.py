"""Tests for native Crypto.com OCO post-fill SL/TP protection."""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.brokers.crypto_com_trade import (
    looks_like_exchange_list_id,
    CryptoComTradeClient,
)
from app.services.tp_sl_order_creator import (
    get_closing_side_from_entry,
    is_native_oco_enabled,
)
from app.services.exchange_sync import ExchangeSyncService
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum


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


def test_looks_like_exchange_list_id():
    assert looks_like_exchange_list_id("6498090546073120100") is True
    assert looks_like_exchange_list_id("oco_5755600491091887888_1710000000") is False
    assert looks_like_exchange_list_id(None) is False
    assert looks_like_exchange_list_id("abc") is False


def test_is_native_oco_enabled_default(monkeypatch):
    monkeypatch.delenv("SLTP_NATIVE_OCO", raising=False)
    assert is_native_oco_enabled() is True
    monkeypatch.setenv("SLTP_NATIVE_OCO", "false")
    assert is_native_oco_enabled() is False


def test_place_oco_sl_tp_dry_run_payload_sides():
    client = CryptoComTradeClient()
    # Long close = SELL
    out = client.place_oco_sl_tp(
        symbol="ETH_USDT",
        side=get_closing_side_from_entry("BUY"),
        tp_price=3000.0,
        sl_price=2700.0,
        qty=0.01,
        dry_run=True,
        source="test",
    )
    assert out["list_id"].startswith("dry_oco_")
    assert out["tp_order_type"] == "LIMIT"
    assert out["sl_order_type"] == "STOP_LIMIT"
    assert out["tp_order_id"]
    assert out["sl_order_id"]

    # Short close = BUY
    out2 = client.place_oco_sl_tp(
        symbol="ETH_USDT",
        side=get_closing_side_from_entry("SELL"),
        tp_price=2500.0,
        sl_price=2800.0,
        qty=0.01,
        dry_run=True,
        source="test",
    )
    assert out2["list_id"].startswith("dry_oco_")


def test_create_sl_tp_impl_uses_native_oco_when_both_missing(db_session, monkeypatch):
    monkeypatch.setenv("SLTP_NATIVE_OCO", "true")
    oco_calls = []
    legacy_sl = []
    legacy_tp = []

    def _oco(**kwargs):
        oco_calls.append(kwargs)
        return {
            "sl_result": {"order_id": "sl-oco-1", "error": None},
            "tp_result": {"order_id": "tp-oco-1", "error": None},
            "oco_group_id": "6498090546073120100",
            "error": None,
            "sl_newly_created": True,
            "tp_newly_created": True,
        }

    def _sl(**kwargs):
        legacy_sl.append(kwargs)
        return {"order_id": "legacy-sl", "error": None}

    def _tp(**kwargs):
        legacy_tp.append(kwargs)
        return {"order_id": "legacy-tp", "error": None}

    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_oco_protection_orders", _oco
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_stop_loss_order", _sl
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_take_profit_order", _tp
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
        lambda db, symbol: (False, None),
    )

    service = ExchangeSyncService()
    result = service._create_sl_tp_impl(
        db=db_session,
        symbol="ETH_USDT",
        side_upper="BUY",
        filled_price_f=100.0,
        filled_qty=1.0,
        order_id="parent-1",
        source="test",
        strict_percentages=False,
        sl_price_override_f=90.0,
        tp_price_override_f=110.0,
    )

    assert len(oco_calls) == 1
    assert not legacy_sl and not legacy_tp
    assert result["oco_group_id"] == "6498090546073120100"
    assert result["sl_result"]["order_id"] == "sl-oco-1"
    assert result["tp_result"]["order_id"] == "tp-oco-1"


def test_create_sl_tp_impl_falls_back_when_oco_fails(db_session, monkeypatch):
    monkeypatch.setenv("SLTP_NATIVE_OCO", "true")
    legacy_sl = []
    legacy_tp = []

    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_oco_protection_orders",
        lambda **kwargs: {
            "sl_result": {"order_id": None, "error": "rejected"},
            "tp_result": {"order_id": None, "error": "rejected"},
            "oco_group_id": None,
            "error": "rejected",
        },
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_stop_loss_order",
        lambda **kwargs: legacy_sl.append(kwargs) or {"order_id": "legacy-sl", "error": None},
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_take_profit_order",
        lambda **kwargs: legacy_tp.append(kwargs) or {"order_id": "legacy-tp", "error": None},
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
        lambda db, symbol: (False, None),
    )

    service = ExchangeSyncService()
    result = service._create_sl_tp_impl(
        db=db_session,
        symbol="ETH_USDT",
        side_upper="BUY",
        filled_price_f=100.0,
        filled_qty=1.0,
        order_id="parent-2",
        source="test",
        strict_percentages=False,
        sl_price_override_f=90.0,
        tp_price_override_f=110.0,
    )
    assert len(legacy_sl) == 1 and len(legacy_tp) == 1
    assert result["sl_result"]["order_id"] == "legacy-sl"


def test_create_sl_tp_impl_skips_oco_for_margin(db_session, monkeypatch):
    monkeypatch.setenv("SLTP_NATIVE_OCO", "true")
    oco_calls = []
    legacy_sl = []

    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_oco_protection_orders",
        lambda **kwargs: oco_calls.append(kwargs) or {"error": "should not run"},
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_stop_loss_order",
        lambda **kwargs: legacy_sl.append(kwargs) or {"order_id": "m-sl", "error": None},
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_take_profit_order",
        lambda **kwargs: {"order_id": "m-tp", "error": None},
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
        lambda db, symbol: (True, 5.0),
    )

    service = ExchangeSyncService()
    service._create_sl_tp_impl(
        db=db_session,
        symbol="BTC_USD",
        side_upper="BUY",
        filled_price_f=60000.0,
        filled_qty=0.001,
        order_id="parent-m",
        source="test",
        strict_percentages=False,
        sl_price_override_f=None,
        tp_price_override_f=None,
    )
    assert not oco_calls
    assert len(legacy_sl) == 1


def test_create_sl_tp_impl_one_leg_uses_legacy_only(db_session, monkeypatch):
    monkeypatch.setenv("SLTP_NATIVE_OCO", "true")
    parent_id = "parent-one-leg"
    db_session.add(
        ExchangeOrder(
            exchange_order_id="existing-sl",
            symbol="ETH_USDT",
            side=OrderSideEnum.SELL,
            order_type="STOP_LIMIT",
            status=OrderStatusEnum.ACTIVE,
            price=Decimal("90"),
            quantity=Decimal("1"),
            parent_order_id=parent_id,
            order_role="STOP_LOSS",
            oco_group_id="oco_parent-one-leg_1",
            exchange_create_time=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    oco_calls = []
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_oco_protection_orders",
        lambda **kwargs: oco_calls.append(kwargs) or {"error": "no"},
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_stop_loss_order",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should reuse SL")),
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_take_profit_order",
        lambda **kwargs: {"order_id": "new-tp", "error": None},
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
        lambda db, symbol: (False, None),
    )

    service = ExchangeSyncService()
    result = service._create_sl_tp_impl(
        db=db_session,
        symbol="ETH_USDT",
        side_upper="BUY",
        filled_price_f=100.0,
        filled_qty=1.0,
        order_id=parent_id,
        source="test",
        strict_percentages=False,
        sl_price_override_f=90.0,
        tp_price_override_f=110.0,
    )
    assert not oco_calls
    assert result["sl_result"]["order_id"] == "existing-sl"
    assert result["tp_result"]["order_id"] == "new-tp"


def test_cancel_order_type_for_limit_tp_leg():
    sib = MagicMock()
    sib.order_type = "LIMIT"
    sib.order_role = "TAKE_PROFIT"
    assert ExchangeSyncService._cancel_order_type_for_sibling(sib) == "LIMIT"


def test_cancel_oco_sibling_soft_check_native_list_id(db_session, monkeypatch):
    list_id = "6498090546073120199"
    filled = ExchangeOrder(
        exchange_order_id="tp-filled",
        symbol="ETH_USDT",
        side=OrderSideEnum.SELL,
        order_type="LIMIT",
        status=OrderStatusEnum.FILLED,
        price=Decimal("110"),
        quantity=Decimal("1"),
        parent_order_id="p1",
        order_role="TAKE_PROFIT",
        oco_group_id=list_id,
        exchange_create_time=datetime.now(timezone.utc),
        exchange_update_time=datetime.now(timezone.utc),
    )
    sibling = ExchangeOrder(
        exchange_order_id="sl-active",
        symbol="ETH_USDT",
        side=OrderSideEnum.SELL,
        order_type="STOP_LIMIT",
        status=OrderStatusEnum.ACTIVE,
        price=Decimal("90"),
        quantity=Decimal("1"),
        parent_order_id="p1",
        order_role="STOP_LOSS",
        oco_group_id=list_id,
        exchange_create_time=datetime.now(timezone.utc),
    )
    db_session.add(filled)
    db_session.add(sibling)
    db_session.commit()

    cancel_calls = []

    class _FakeClient:
        def get_order_detail(self, order_id):
            return {"result": {"status": "CANCELLED", "order_id": order_id}}

        def cancel_order(self, *args, **kwargs):
            cancel_calls.append((args, kwargs))
            return {"error": "should not be called"}

    monkeypatch.setattr(
        "app.services.brokers.crypto_com_trade.trade_client",
        _FakeClient(),
    )
    monkeypatch.setattr(
        "app.services.exchange_sync.is_recent_exchange_event",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app.services.live_trading_gate.assert_exchange_mutation_allowed",
        lambda *a, **k: None,
    )

    service = ExchangeSyncService()
    ok = service._cancel_oco_sibling(db_session, filled)
    assert ok is True
    assert not cancel_calls
    db_session.refresh(sibling)
    assert sibling.status == OrderStatusEnum.CANCELLED
