"""Tests for /orders/history status filter and exclude_cancelled pagination."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _order(
    order_id: str,
    status: OrderStatusEnum,
    *,
    minutes_ago: int = 0,
) -> ExchangeOrder:
    ts = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc) - timedelta(minutes=minutes_ago)
    return ExchangeOrder(
        exchange_order_id=order_id,
        symbol="BTC_USDT",
        side=OrderSideEnum.BUY,
        order_type="LIMIT",
        status=status,
        price=Decimal("100"),
        quantity=Decimal("1"),
        exchange_create_time=ts,
        exchange_update_time=ts,
    )


def test_exclude_cancelled_returns_only_filled(db_session):
    # Interleave cancelled and filled so client-side filtering of first page would drop filled.
    for i in range(5):
        db_session.add(_order(f"c-{i}", OrderStatusEnum.CANCELLED, minutes_ago=i * 2))
        db_session.add(_order(f"f-{i}", OrderStatusEnum.FILLED, minutes_ago=i * 2 + 1))
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        mixed = client.get("/api/orders/history?limit=5&offset=0")
        assert mixed.status_code == 200
        mixed_body = mixed.json()
        assert mixed_body["count"] == 5
        assert any(o["status"] == "CANCELLED" for o in mixed_body["orders"])

        filled_only = client.get("/api/orders/history?limit=5&offset=0&exclude_cancelled=true")
        assert filled_only.status_code == 200
        body = filled_only.json()
        assert body["count"] == 5
        assert all(o["status"] == "FILLED" for o in body["orders"])
        assert body["total"] == 5
        assert body["has_more"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_exclude_cancelled_pagination_has_more(db_session):
    for i in range(12):
        db_session.add(_order(f"fill-{i}", OrderStatusEnum.FILLED, minutes_ago=i))
        db_session.add(_order(f"canc-{i}", OrderStatusEnum.CANCELLED, minutes_ago=i))
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        page1 = client.get("/api/orders/history?limit=5&offset=0&exclude_cancelled=true")
        assert page1.status_code == 200
        body1 = page1.json()
        assert body1["count"] == 5
        assert body1["has_more"] is True
        assert all(o["status"] == "FILLED" for o in body1["orders"])

        page2 = client.get("/api/orders/history?limit=5&offset=5&exclude_cancelled=true")
        assert page2.status_code == 200
        body2 = page2.json()
        assert body2["count"] == 5
        assert body2["has_more"] is True

        page3 = client.get("/api/orders/history?limit=5&offset=10&exclude_cancelled=true")
        assert page3.status_code == 200
        body3 = page3.json()
        assert body3["count"] == 2
        assert body3["has_more"] is False

        ids = {o["order_id"] for o in body1["orders"] + body2["orders"] + body3["orders"]}
        assert len(ids) == 12
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_status_filter_filled(db_session):
    db_session.add(_order("a", OrderStatusEnum.FILLED, minutes_ago=0))
    db_session.add(_order("b", OrderStatusEnum.CANCELLED, minutes_ago=1))
    db_session.add(_order("c", OrderStatusEnum.REJECTED, minutes_ago=2))
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.get("/api/orders/history?status=FILLED")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["orders"][0]["order_id"] == "a"
    finally:
        app.dependency_overrides.pop(get_db, None)
