import sys
import time
import types
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes_dashboard import get_dashboard_state
from app.database import Base
from app.models.exchange_balance import ExchangeBalance
from app.models.portfolio import PortfolioBalance, PortfolioSnapshot
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum


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


@pytest.fixture(autouse=True)
def stub_backend_services(monkeypatch):
    """Provide lightweight stubs for background services used by the dashboard route."""
    stub_sync = types.SimpleNamespace(
        is_running=True,
        last_sync=datetime.now(timezone.utc),
        sync_interval=5,
    )
    monkeypatch.setattr("app.api.routes_dashboard.exchange_sync_service", stub_sync)

    stub_trade_client = types.SimpleNamespace(
        get_open_orders=lambda: {"data": []}
    )
    monkeypatch.setattr("app.api.routes_dashboard.trade_client", stub_trade_client)

    stub_monitor_module = types.SimpleNamespace(
        signal_monitor_service=types.SimpleNamespace(is_running=True)
    )
    monkeypatch.setitem(sys.modules, "app.services.signal_monitor", stub_monitor_module)
    yield

def test_dashboard_state_uses_portfolio_cache(db_session, monkeypatch):
    """Balances in dashboard state should come from portfolio cache without frontend fallbacks."""
    # Existing exchange balance
    balance = ExchangeBalance(
        asset="ETH",
        free=Decimal("1.25"),
        locked=Decimal("0.25"),
        total=Decimal("1.50"),
    )
    db_session.add(balance)

    # Cached portfolio valuation and snapshot
    portfolio_balance = PortfolioBalance(
        currency="ETH",
        balance=Decimal("1.50"),
        usd_value=4500.0,
    )
    snapshot = PortfolioSnapshot(
        total_usd=4500.0,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(portfolio_balance)
    db_session.add(snapshot)
    db_session.commit()

    # Ensure we do not accidentally trigger an external refresh
    refresh_called = {"value": False}

    def fake_refresh(_db):
        refresh_called["value"] = True
        return {"success": True}

    from app.services.portfolio_cache import get_portfolio_summary as real_get_summary

    summary_before = real_get_summary(db_session)
    assert summary_before["balances"], "Precondition: cached portfolio balances must exist for test"

    summary_calls = {"count": 0}

    def wrapped_get_summary(db):
        summary_calls["count"] += 1
        return real_get_summary(db)

    monkeypatch.setattr("app.api.routes_dashboard.update_portfolio_cache", fake_refresh)
    monkeypatch.setattr("app.api.routes_dashboard.get_portfolio_summary", wrapped_get_summary)

    response = get_dashboard_state(db=db_session)

    assert response["source"] == "portfolio_cache"
    assert response["total_usd_value"] == pytest.approx(4500.0)
    assert response["balances"], "Balances array should not be empty"
    eth_balance = next((item for item in response["balances"] if item["asset"] == "ETH"), None)
    assert eth_balance is not None
    assert eth_balance["usd_value"] == pytest.approx(4500.0)
    assert eth_balance["free"] == pytest.approx(1.25)
    assert eth_balance["locked"] == pytest.approx(0.25)
    assert summary_calls["count"] >= 1, "Route should consult portfolio summary"


def test_dashboard_state_refreshes_empty_cache(db_session, monkeypatch):
    """When the cache is empty, the route should trigger a refresh and use the refreshed data."""
    # Exchange balance without USD valuation yet
    balance = ExchangeBalance(
        asset="BTC",
        free=Decimal("0.5"),
        locked=Decimal("0.1"),
        total=Decimal("0.6"),
    )
    db_session.add(balance)
    db_session.commit()

    refresh_called = {"value": False}

    def fake_update(db):
        refresh_called["value"] = True
        return {"success": True}

    portfolio_data = {
        "balances": [
            {"currency": "BTC", "balance": 0.6, "usd_value": 36000.0}
        ],
        "total_usd": 36000.0,
        "last_updated": time.time(),
    }

    summary_calls = {"count": 0}

    def fake_summary(db):
        summary_calls["count"] += 1
        if summary_calls["count"] == 1:
            return {"balances": [], "total_usd": 0.0, "last_updated": None}
        return portfolio_data

    monkeypatch.setattr("app.api.routes_dashboard.update_portfolio_cache", fake_update)
    monkeypatch.setattr("app.api.routes_dashboard.get_portfolio_summary", fake_summary)

    response = get_dashboard_state(db=db_session)

    assert refresh_called["value"], "Cache refresh should run when summary is empty"
    assert response["source"] == "portfolio_cache"
    assert response["total_usd_value"] == pytest.approx(36000.0)
    btc = next((b for b in response["balances"] if b["asset"] == "BTC"), None)
    assert btc is not None
    assert btc["usd_value"] == pytest.approx(36000.0)


def test_dashboard_state_refreshes_stale_cache(db_session, monkeypatch):
    """Cache older than the staleness threshold should trigger an update."""
    # Existing balance
    balance = ExchangeBalance(
        asset="SOL",
        free=Decimal("10"),
        locked=Decimal("0"),
        total=Decimal("10"),
    )
    db_session.add(balance)
    db_session.commit()

    refresh_called = {"value": False}

    def fake_update(db):
        refresh_called["value"] = True
        return {"success": True}

    stale_ts = time.time() - 120  # Older than 60s threshold
    summary_responses = [
        {
            "balances": [
                {"currency": "SOL", "balance": 10.0, "usd_value": 900.0}
            ],
            "total_usd": 900.0,
            "last_updated": stale_ts,
        },
        {
            "balances": [
                {"currency": "SOL", "balance": 10.0, "usd_value": 900.0}
            ],
            "total_usd": 900.0,
            "last_updated": time.time(),
        },
    ]
    latest_response = summary_responses[-1]

    def fake_summary(db):
        nonlocal latest_response, summary_responses
        if summary_responses:
            latest_response = summary_responses.pop(0)
        return latest_response

    monkeypatch.setattr("app.api.routes_dashboard.update_portfolio_cache", fake_update)
    monkeypatch.setattr("app.api.routes_dashboard.get_portfolio_summary", fake_summary)

    response = get_dashboard_state(db=db_session)

    assert refresh_called["value"], "Stale cache should trigger refresh"
    assert response["total_usd_value"] == pytest.approx(900.0)
    sol = next((b for b in response["balances"] if b["asset"] == "SOL"), None)
    assert sol is not None
    assert sol["usd_value"] == pytest.approx(900.0)


def test_dashboard_state_merges_cached_currency_without_exchange_balance(db_session, monkeypatch):
    """Currencies present only in the portfolio cache should still appear in the response."""
    # No exchange balance rows for ADA
    summary = {
        "balances": [
            {"currency": "ADA", "balance": 250.0, "usd_value": 150.0}
        ],
        "total_usd": 150.0,
        "last_updated": time.time(),
    }

    def fake_update(_db):
        raise AssertionError("update_portfolio_cache should not be invoked when cache has data")

    monkeypatch.setattr("app.api.routes_dashboard.get_portfolio_summary", lambda db: summary)
    monkeypatch.setattr("app.api.routes_dashboard.update_portfolio_cache", fake_update)

    response = get_dashboard_state(db=db_session)

    ada = next((b for b in response["balances"] if b["asset"] == "ADA"), None)
    assert ada is not None
    assert ada["balance"] == pytest.approx(250.0)
    assert ada["usd_value"] == pytest.approx(150.0)
    assert response["total_usd_value"] == pytest.approx(150.0)


def test_dashboard_state_uses_database_open_orders(db_session, monkeypatch):
    """Open orders should be sourced from the database without calling the external API when present."""
    order = ExchangeOrder(
        exchange_order_id="12345",
        client_oid="client-1",
        symbol="ETH_USDT",
        side=OrderSideEnum.BUY,
        order_type="LIMIT",
        status=OrderStatusEnum.NEW,
        price=Decimal("3000"),
        quantity=Decimal("1"),
        cumulative_quantity=Decimal("0"),
        cumulative_value=Decimal("0"),
        avg_price=None,
        exchange_create_time=datetime.now(timezone.utc),
        exchange_update_time=datetime.now(timezone.utc),
    )
    db_session.add(order)
    db_session.commit()

    # Portfolio summary can be empty but should be considered fresh enough to avoid refresh
    summary = {"balances": [], "total_usd": 0.0, "last_updated": time.time()}
    monkeypatch.setattr("app.api.routes_dashboard.get_portfolio_summary", lambda db: summary)

    api_called = {"count": 0}

    def fake_update(_db):
        raise AssertionError("update_portfolio_cache should not be called when summary already provided")

    def fake_get_open_orders():
        api_called["count"] += 1
        raise AssertionError("API fallback should not run when DB has open orders")

    monkeypatch.setattr("app.api.routes_dashboard.update_portfolio_cache", fake_update)
    monkeypatch.setattr("app.api.routes_dashboard.trade_client", types.SimpleNamespace(get_open_orders=fake_get_open_orders))

    response = get_dashboard_state(db=db_session)

    assert api_called["count"] == 0
    assert response["open_orders"], "Open orders should include the DB order"
    entry = next((o for o in response["open_orders"] if o["exchange_order_id"] == "12345"), None)
    assert entry is not None
    assert entry["symbol"] == "ETH_USDT"
    assert entry["side"] == "BUY"
    assert entry["order_type"] == "LIMIT"
