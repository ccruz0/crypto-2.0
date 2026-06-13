"""Tests for open orders cache/DB fallback resolver."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.open_orders import UnifiedOpenOrder
from app.services.open_orders_cache import clear_open_orders_cache, store_unified_open_orders
from app.services.open_orders_resolver import resolve_open_orders
from app.services.open_orders_sync_status import (
    record_open_orders_sync_success,
    reset_open_orders_sync_status_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_open_orders_state():
    clear_open_orders_cache()
    reset_open_orders_sync_status_for_tests()
    yield
    clear_open_orders_cache()
    reset_open_orders_sync_status_for_tests()


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


def _btc_usd_db_order(**overrides) -> ExchangeOrder:
    defaults = dict(
        exchange_order_id="5755600489253467765",
        symbol="BTC_USD",
        side=OrderSideEnum.SELL,
        order_type="LIMIT",
        status=OrderStatusEnum.ACTIVE,
        price=Decimal("100000"),
        quantity=Decimal("0.001"),
        exchange_create_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        exchange_update_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return ExchangeOrder(**defaults)


def _btc_usd_unified_order() -> UnifiedOpenOrder:
    return UnifiedOpenOrder(
        order_id="5755600489253467765",
        symbol="BTC_USD",
        side="SELL",
        order_type="LIMIT",
        status="ACTIVE",
        quantity=Decimal("0.001"),
        price=Decimal("100000"),
        is_trigger=False,
        created_at="2024-01-01T00:00:00+00:00",
    )


def test_memory_cache_empty_db_has_active_order_returns_db_order(db_session):
    db_session.add(_btc_usd_db_order())
    db_session.commit()

    resolved = resolve_open_orders(db_session)

    assert len(resolved.orders) == 1
    assert resolved.orders[0].order_id == "5755600489253467765"
    assert resolved.orders[0].symbol == "BTC_USD"
    assert resolved.source == "database_fallback"
    assert resolved.sync_status == "stale_cache_db_fallback"
    assert resolved.data_verified is True


def test_cache_stale_db_has_active_order_returns_db_with_metadata(db_session):
    db_session.add(_btc_usd_db_order())
    db_session.commit()

    resolved = resolve_open_orders(db_session)

    assert len(resolved.orders) == 1
    assert resolved.sync_status == "stale_cache_db_fallback"
    assert resolved.data_verified is True
    assert resolved.source == "database_fallback"


def test_cache_ok_memory_has_orders_memory_wins(db_session):
    db_session.add(_btc_usd_db_order())
    db_session.commit()

    store_unified_open_orders([_btc_usd_unified_order()])
    record_open_orders_sync_success(order_count=1)

    resolved = resolve_open_orders(db_session)

    assert len(resolved.orders) == 1
    assert resolved.source == "crypto_com_api"
    assert resolved.sync_status == "ok"
    assert resolved.data_verified is True


def test_db_fallback_preserves_btc_usd(db_session):
    db_session.add(_btc_usd_db_order())
    db_session.commit()

    resolved = resolve_open_orders(db_session)

    assert resolved.orders[0].symbol == "BTC_USD"
    assert resolved.orders[0].side == "SELL"
    assert resolved.orders[0].status == "ACTIVE"


def test_no_db_orders_stale_cache_returns_empty_unverified(db_session):
    resolved = resolve_open_orders(db_session)

    assert resolved.orders == []
    assert resolved.sync_status == "stale"
    assert resolved.data_verified is False


def test_orders_open_api_db_fallback(db_session):
    db_session.add(_btc_usd_db_order())
    db_session.commit()

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/orders/open")
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 1
        assert payload["source"] == "database_fallback"
        assert payload["sync_status"] == "stale_cache_db_fallback"
        assert payload["data_verified"] is True
        order = payload["orders"][0]
        assert order["order_id"] == "5755600489253467765"
        assert order["instrument_name"] == "BTC_USD"
    finally:
        app.dependency_overrides.clear()


def test_dashboard_open_orders_summary_db_fallback(db_session):
    db_session.add(_btc_usd_db_order())
    db_session.commit()

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/dashboard/open-orders-summary")
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 1
        assert payload["source"] == "database_fallback"
        assert payload["sync_status"] == "stale_cache_db_fallback"
        assert payload["data_verified"] is True
        assert payload["orders"][0]["symbol"] == "BTC_USD"
    finally:
        app.dependency_overrides.clear()


def test_ok_db_fallback_when_cache_sync_ok_but_empty(db_session):
    db_session.add(_btc_usd_db_order())
    db_session.commit()
    record_open_orders_sync_success(order_count=0)

    resolved = resolve_open_orders(db_session)

    assert len(resolved.orders) == 1
    assert resolved.sync_status == "ok_db_fallback"
    assert resolved.source == "database_fallback"
    assert resolved.data_verified is True
