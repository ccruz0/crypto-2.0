import time
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

from app.database import Base
from app.models.exchange_balance import ExchangeBalance
# Import models to ensure they're registered with Base.metadata before table creation
from app.models.exchange_order import ExchangeOrder
from app.models.telegram_message import TelegramMessage
from app.models.signal_throttle import SignalThrottleState
from app.services.exchange_sync import ExchangeSyncService


@pytest.fixture
def db_session():
    """Provide an isolated in-memory database session for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Create tables manually, skipping indexes to avoid conflicts
    # Create each table individually to handle errors gracefully
    for table in Base.metadata.tables.values():
        try:
            table.create(bind=engine, checkfirst=True)
        except OperationalError as e:
            if "already exists" not in str(e).lower():
                raise
    
    # Create indexes separately, ignoring "already exists" errors
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            try:
                index.create(bind=engine)
            except OperationalError as e:
                if "already exists" not in str(e).lower():
                    raise

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
    service.sync_balances(db_session)

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


def test_sync_balances_numeric_type_conversion(db_session, monkeypatch, caplog):
    """sync_balances should handle float/Decimal conversion without TypeError and log numeric conversions."""
    # Stub portfolio cache to return balances with various numeric formats
    from app.services import portfolio_cache

    def fake_get_portfolio_summary(_db):
        return {
            "balances": [
                # String format (common from API)
                {"currency": "BTC", "balance": "1.5", "available": "1.2"},
                # Float format (less common but possible)
                {"currency": "ETH", "balance": 2.0, "available": 1.8},
                # Invalid format that should be handled gracefully
                {"currency": "ADA", "balance": "invalid", "available": "1.0"},
            ]
        }

    def fake_update_portfolio_cache(_db):
        return {"success": True}

    monkeypatch.setattr(portfolio_cache, "get_portfolio_summary", fake_get_portfolio_summary)
    monkeypatch.setattr(portfolio_cache, "update_portfolio_cache", fake_update_portfolio_cache)

    # Prevent direct API usage during this test
    monkeypatch.setattr("app.services.exchange_sync.trade_client", _StubTradeClient())

    service = ExchangeSyncService()
    # This should not raise TypeError: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'
    service.sync_balances(db_session)

    # Verify balances were created with correct values
    btc_balance = db_session.query(ExchangeBalance).filter_by(asset="BTC").one()
    assert btc_balance.total == Decimal("1.5")
    assert btc_balance.free == Decimal("1.5")
    assert btc_balance.locked == Decimal("0")

    eth_balance = db_session.query(ExchangeBalance).filter_by(asset="ETH").one()
    assert eth_balance.total == Decimal("2.0")
    assert eth_balance.free == Decimal("2.0")
    assert eth_balance.locked == Decimal("0.2")

    # ADA should be skipped due to invalid balance
    ada_balance = db_session.query(ExchangeBalance).filter_by(asset="ADA").first()
    assert ada_balance is None  # Should not exist

    # Check that numeric conversion logs were emitted for string->Decimal conversions
    log_messages = [record.message for record in caplog.records]
    numeric_logs = [msg for msg in log_messages if "[EXCHANGE_SYNC_NUMERIC]" in msg]
    assert len(numeric_logs) >= 2  # At least BTC free and total conversions


def test_order_status_mapping_with_unknown_statuses(db_session, monkeypatch):
    """Test that unknown statuses are mapped to UNKNOWN, not FILLED."""
    from app.models.exchange_order import OrderStatusEnum

    # Mock order data with unknown status
    mock_order_data = {
        'order_id': 'test-123',
        'status': 'SOME_UNKNOWN_STATUS',
        'quantity': 1.0,
        'cumulative_quantity': 0
    }

    # Stub trade client to return our mock order
    from app.services import exchange_sync

    def mock_get_open_orders():
        return {'data': [mock_order_data]}

    monkeypatch.setattr(exchange_sync.trade_client, 'get_open_orders', mock_get_open_orders)

    # Create existing order in DB
    from app.models.exchange_order import ExchangeOrder, OrderSideEnum
    existing_order = ExchangeOrder(
        exchange_order_id='test-123',
        symbol='BTC_USDT',
        side=OrderSideEnum.BUY,
        order_type='LIMIT',
        status=OrderStatusEnum.NEW,
        price=50000.0,
        quantity=1.0
    )
    db_session.add(existing_order)
    db_session.commit()

    # Run sync
    service = exchange_sync.ExchangeSyncService()
    service.sync_open_orders(db_session)

    # Verify status was set to UNKNOWN, not FILLED
    updated_order = db_session.query(ExchangeOrder).filter_by(exchange_order_id='test-123').first()
    assert updated_order.status == OrderStatusEnum.UNKNOWN


def test_order_status_mapping_cancelled_with_partial_fill(db_session, monkeypatch):
    """Test that CANCELLED orders with cumulative_quantity > 0 are treated as PARTIALLY_FILLED."""
    from app.models.exchange_order import OrderStatusEnum

    # Mock order data with cancelled status but partial fill
    mock_order_data = {
        'order_id': 'test-456',
        'status': 'CANCELLED',
        'quantity': 1.0,
        'cumulative_quantity': 0.5  # Partial fill before cancellation
    }

    # Stub trade client
    from app.services import exchange_sync

    def mock_get_open_orders():
        return {'data': [mock_order_data]}

    monkeypatch.setattr(exchange_sync.trade_client, 'get_open_orders', mock_get_open_orders)

    # Create existing order in DB
    from app.models.exchange_order import ExchangeOrder, OrderSideEnum
    existing_order = ExchangeOrder(
        exchange_order_id='test-456',
        symbol='BTC_USDT',
        side=OrderSideEnum.BUY,
        order_type='LIMIT',
        status=OrderStatusEnum.NEW,
        price=50000.0,
        quantity=1.0
    )
    db_session.add(existing_order)
    db_session.commit()

    # Run sync
    service = exchange_sync.ExchangeSyncService()
    service.sync_open_orders(db_session)

    # Verify status was set to PARTIALLY_FILLED
    updated_order = db_session.query(ExchangeOrder).filter_by(exchange_order_id='test-456').first()
    assert updated_order.status == OrderStatusEnum.PARTIALLY_FILLED


def test_order_status_mapping_canceled_with_partial_fill(db_session, monkeypatch):
    """Test that CANCELED (one L) orders with cumulative_quantity > 0 are treated as PARTIALLY_FILLED."""
    from app.models.exchange_order import OrderStatusEnum

    # Mock order data with canceled status (one L) but partial fill
    mock_order_data = {
        'order_id': 'test-789',
        'status': 'CANCELED',  # One L spelling
        'quantity': 1.0,
        'cumulative_quantity': 0.3  # Partial fill before cancellation
    }

    # Stub trade client
    from app.services import exchange_sync

    def mock_get_open_orders():
        return {'data': [mock_order_data]}

    monkeypatch.setattr(exchange_sync.trade_client, 'get_open_orders', mock_get_open_orders)

    # Create existing order in DB
    from app.models.exchange_order import ExchangeOrder, OrderSideEnum
    existing_order = ExchangeOrder(
        exchange_order_id='test-789',
        symbol='ETH_USDT',
        side=OrderSideEnum.BUY,
        order_type='LIMIT',
        status=OrderStatusEnum.NEW,
        price=3000.0,
        quantity=1.0
    )
    db_session.add(existing_order)
    db_session.commit()

    # Run sync
    service = exchange_sync.ExchangeSyncService()
    service.sync_open_orders(db_session)

    # Verify status was set to PARTIALLY_FILLED (not CANCELLED)
    updated_order = db_session.query(ExchangeOrder).filter_by(exchange_order_id='test-789').first()
    assert updated_order.status == OrderStatusEnum.PARTIALLY_FILLED


def test_order_status_mapping_canceled_with_full_fill(db_session, monkeypatch):
    """Test that CANCELED orders with cumulative_quantity >= quantity are treated as FILLED."""
    from app.models.exchange_order import OrderStatusEnum

    # Mock order data with canceled status but full fill
    mock_order_data = {
        'order_id': 'test-999',
        'status': 'CANCELED',
        'quantity': 1.0,
        'cumulative_quantity': 1.0  # Full fill before cancellation
    }

    # Stub trade client
    from app.services import exchange_sync

    def mock_get_open_orders():
        return {'data': [mock_order_data]}

    monkeypatch.setattr(exchange_sync.trade_client, 'get_open_orders', mock_get_open_orders)

    # Create existing order in DB
    from app.models.exchange_order import ExchangeOrder, OrderSideEnum
    existing_order = ExchangeOrder(
        exchange_order_id='test-999',
        symbol='SOL_USDT',
        side=OrderSideEnum.BUY,
        order_type='LIMIT',
        status=OrderStatusEnum.NEW,
        price=100.0,
        quantity=1.0
    )
    db_session.add(existing_order)
    db_session.commit()

    # Run sync
    service = exchange_sync.ExchangeSyncService()
    service.sync_open_orders(db_session)

    # Verify status was set to FILLED (not CANCELLED)
    updated_order = db_session.query(ExchangeOrder).filter_by(exchange_order_id='test-999').first()
    assert updated_order.status == OrderStatusEnum.FILLED


def test_order_status_mapping_unknown_with_zero_quantity(db_session, monkeypatch):
    """Test that unknown status with cumulative_quantity=0 maps to UNKNOWN."""
    from app.models.exchange_order import OrderStatusEnum

    # Mock order data with unknown status and no fills
    mock_order_data = {
        'order_id': 'test-unknown',
        'status': 'UNKNOWN_STATUS_XYZ',  # Unknown status
        'quantity': 1.0,
        'cumulative_quantity': 0.0  # No fills
    }

    # Stub trade client
    from app.services import exchange_sync

    def mock_get_open_orders():
        return {'data': [mock_order_data]}

    monkeypatch.setattr(exchange_sync.trade_client, 'get_open_orders', mock_get_open_orders)

    # Create existing order in DB
    from app.models.exchange_order import ExchangeOrder, OrderSideEnum
    existing_order = ExchangeOrder(
        exchange_order_id='test-unknown',
        symbol='ADA_USDT',
        side=OrderSideEnum.BUY,
        order_type='LIMIT',
        status=OrderStatusEnum.NEW,
        price=0.5,
        quantity=1.0
    )
    db_session.add(existing_order)
    db_session.commit()

    # Run sync
    service = exchange_sync.ExchangeSyncService()
    service.sync_open_orders(db_session)

    # Verify status was set to UNKNOWN
    updated_order = db_session.query(ExchangeOrder).filter_by(exchange_order_id='test-unknown').first()
    assert updated_order.status == OrderStatusEnum.UNKNOWN


def test_stop_limit_payload_construction():
    """Test that STOP_LIMIT order payloads are constructed correctly with proper fields."""
    from backend.app.services.brokers.crypto_com_trade import CryptoComTradeClient
    from unittest.mock import patch

    # Mock the client to avoid actual API calls
    client = CryptoComTradeClient.__new__(CryptoComTradeClient)  # Create without __init__
    client.api_key = "test_key"
    client.api_secret = "test_secret"

    # Mock _get_instrument_metadata
    with patch.object(client, '_get_instrument_metadata') as mock_meta:
        mock_meta.return_value = {
            "quantity_decimals": 2,
            "qty_tick_size": "0.01",
            "min_quantity": "0.01"
        }

        # Mock normalize_price and normalize_quantity
        with patch.object(client, 'normalize_price') as mock_norm_price, \
             patch.object(client, 'normalize_quantity') as mock_norm_qty:

            mock_norm_price.return_value = "50000.00"
            mock_norm_qty.return_value = "0.01"

            # Test STOP_LIMIT order placement
            with patch('backend.app.services.brokers.crypto_com_trade.http_post') as mock_post:
                mock_post.return_value = type('MockResponse', (), {'status_code': 200, 'json': lambda: {'result': {'order_id': '123'}}})()

                result = client.place_stop_loss_order(
                    symbol="BTC_USDT",
                    side="SELL",
                    price=50000.0,
                    qty=0.01,
                    trigger_price=49000.0,
                    dry_run=False
                )

                # Verify the API was called
                assert mock_post.called
                call_args = mock_post.call_args
                payload = call_args[1]['json']  # The JSON payload

                # Verify required fields are present
                assert payload['method'] == 'private/create-order'
                params = payload['params']
                assert params['instrument_name'] == 'BTC_USDT'
                assert params['side'] == 'SELL'
                assert params['type'] == 'STOP_LIMIT'
                assert 'price' in params
                assert 'quantity' in params
                assert 'trigger_price' in params
                assert 'ref_price' in params
                assert params['time_in_force'] == 'GTC'  # Should be GTC, not GOOD_TILL_CANCEL


def test_sync_balances_handles_mixed_float_decimal_arithmetic(db_session, monkeypatch):
    """Test that reproduces the original TypeError crash and verifies it's fixed."""
    from decimal import Decimal

    # Create a scenario that would have crashed before: existing Decimal balance + float arithmetic
    existing = ExchangeBalance(asset="BTC", free=Decimal("1.0"), locked=Decimal("0.5"), total=Decimal("1.5"))
    db_session.add(existing)
    db_session.commit()

    # Stub portfolio cache to return data that would trigger the arithmetic
    from app.services import portfolio_cache

    def fake_get_portfolio_summary(_db):
        return {
            "balances": [
                # This would cause float - Decimal arithmetic in the old code
                {"currency": "BTC", "balance": "2.0", "available": "1.8"},  # 2.0 - 1.8 = 0.2 locked
            ]
        }

    def fake_update_portfolio_cache(_db):
        return {"success": True}

    monkeypatch.setattr(portfolio_cache, "get_portfolio_summary", fake_get_portfolio_summary)
    monkeypatch.setattr(portfolio_cache, "update_portfolio_cache", fake_update_portfolio_cache)
    monkeypatch.setattr("app.services.exchange_sync.trade_client", _StubTradeClient())

    service = ExchangeSyncService()

    # This would have raised: TypeError: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'
    # Now it should work fine
    service.sync_balances(db_session)

    # Verify the balance was updated correctly
    btc_balance = db_session.query(ExchangeBalance).filter_by(asset="BTC").one()
    assert btc_balance.total == Decimal("2.0")
    assert btc_balance.free == Decimal("1.8")
    assert btc_balance.locked == Decimal("0.2")  # 2.0 - 1.8
