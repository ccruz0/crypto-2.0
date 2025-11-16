import asyncio
import time
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_balance import ExchangeBalance
from app.services.exchange_sync import ExchangeSyncService


@pytest.fixture
def db_session():
    """Provide an isolated in-memory database session for each test."""
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


class _StubTradeClient:
    def get_account_summary(self):
        raise AssertionError("Balance sync should not call external account summary in this test")


def test_sync_balances_zeroes_missing_assets(db_session, monkeypatch):
    """sync_balances should zero-out assets that disappear from the payload."""
    # Existing balance that should be zeroed after sync
    existing = ExchangeBalance(asset="BTC", free=Decimal("1"), locked=Decimal("0"), total=Decimal("1"))
    db_session.add(existing)
    db_session.commit()

    # Stub portfolio cache to return only ETH balances
    from app.services import portfolio_cache

    def fake_get_portfolio_summary(_db):
        return {
            "balances": [
                {"currency": "ETH", "balance": "2.0", "available": "1.5"},
            ]
        }

    def fake_update_portfolio_cache(_db):
        return {"success": True}

    monkeypatch.setattr(portfolio_cache, "get_portfolio_summary", fake_get_portfolio_summary)
    monkeypatch.setattr(portfolio_cache, "update_portfolio_cache", fake_update_portfolio_cache)

    # Prevent direct API usage during this test
    monkeypatch.setattr("app.services.exchange_sync.trade_client", _StubTradeClient())

    service = ExchangeSyncService()
    asyncio.run(service.sync_balances(db_session))

    eth_balance = db_session.query(ExchangeBalance).filter_by(asset="ETH").one()
    assert float(eth_balance.total) == pytest.approx(2.0)
    assert float(eth_balance.free) == pytest.approx(2.0)

    btc_balance = db_session.query(ExchangeBalance).filter_by(asset="BTC").one()
    assert float(btc_balance.total) == 0.0
    assert float(btc_balance.free) == 0.0
    assert float(btc_balance.locked) == 0.0


def test_purge_stale_processed_orders():
    """Old processed order ids should be purged while recent ones remain."""
    service = ExchangeSyncService()
    service.processed_order_ids = {
        "fresh": time.time(),
        "stale": time.time() - 1200,  # 20 minutes ago
    }

    service._purge_stale_processed_orders()

    assert "fresh" in service.processed_order_ids
    assert "stale" not in service.processed_order_ids
