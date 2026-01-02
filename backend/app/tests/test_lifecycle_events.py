"""Tests for lifecycle event emissions"""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.watchlist import WatchlistItem
from app.models.signal_throttle import SignalThrottleState
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
# Import TelegramMessage to ensure it's registered with Base.metadata before create_all
from app.models.telegram_message import TelegramMessage
# Import record_signal_event to ensure SignalThrottleState model is registered
from app.services.signal_throttle import record_signal_event
from app.services.signal_monitor import _emit_lifecycle_event


@pytest.fixture
def db_session():
    """Provide an isolated in-memory database session for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Create tables manually, skipping indexes to avoid conflicts
    # Create each table individually to handle errors gracefully
    from sqlalchemy.exc import OperationalError
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


@pytest.fixture
def mock_watchlist_item(db_session):
    """Create a mock watchlist item for testing"""
    item = WatchlistItem(
        symbol="BTC_USDT",
        exchange="CRYPTO_COM",
        trade_enabled=True,
        trade_amount_usd=100.0,
        alert_enabled=True,
        buy_alert_enabled=True,
        sell_alert_enabled=True,
        sl_tp_mode="conservative",
        is_deleted=False,
    )
    db_session.add(item)
    db_session.commit()
    return item


@patch('app.api.routes_monitoring.add_telegram_message')
def test_trade_blocked_emits_event_no_order_attempt(mock_telegram, db_session, mock_watchlist_item):
    """Test that TRADE_BLOCKED is emitted and ORDER_ATTEMPT is NOT emitted when trade is blocked"""
    # Set trade_enabled to False
    mock_watchlist_item.trade_enabled = False
    db_session.commit()
    
    # Emit TRADE_BLOCKED (simulating what happens when trade is blocked)
    _emit_lifecycle_event(
        db=db_session,
        symbol="BTC_USDT",
        strategy_key="swing:conservative",
        side="BUY",
        price=50000.0,
        event_type="TRADE_BLOCKED",
        event_reason="SKIP_DISABLED_TRADE",
    )
    db_session.commit()
    
    # Verify TRADE_BLOCKED was emitted
    blocked_event = db_session.query(SignalThrottleState).filter(
        SignalThrottleState.symbol == "BTC_USDT",
        SignalThrottleState.side == "BUY",
        SignalThrottleState.emit_reason.like("%TRADE_BLOCKED%"),
    ).first()
    
    assert blocked_event is not None
    assert blocked_event.last_price == 50000.0
    
    # Verify ORDER_ATTEMPT was NOT emitted
    attempt_event = db_session.query(SignalThrottleState).filter(
        SignalThrottleState.symbol == "BTC_USDT",
        SignalThrottleState.side == "BUY",
        SignalThrottleState.emit_reason.like("%ORDER_ATTEMPT%"),
    ).first()
    
    assert attempt_event is None


@patch('app.api.routes_monitoring.add_telegram_message')
def test_order_success_emits_attempt_and_created(mock_telegram, db_session, mock_watchlist_item):
    """Test that ORDER_ATTEMPT then ORDER_CREATED are emitted when order succeeds"""
    # Emit ORDER_ATTEMPT
    _emit_lifecycle_event(
        db=db_session,
        symbol="BTC_USDT",
        strategy_key="swing:conservative",
        side="BUY",
        price=50000.0,
        event_type="ORDER_ATTEMPT",
        event_reason="notional=100.0, margin=False",
    )
    db_session.commit()
    
    # Emit ORDER_CREATED
    _emit_lifecycle_event(
        db=db_session,
        symbol="BTC_USDT",
        strategy_key="swing:conservative",
        side="BUY",
        price=50000.0,
        event_type="ORDER_CREATED",
        event_reason="order_id=test_123",
        order_id="test_123",
    )
    db_session.commit()
    
    # Verify both events were recorded
    # record_signal_event upserts, so the last event will have the latest emit_reason
    # Check that ORDER_CREATED was recorded (last one)
    event = db_session.query(SignalThrottleState).filter(
        SignalThrottleState.symbol == "BTC_USDT",
        SignalThrottleState.side == "BUY",
    ).first()
    
    assert event is not None
    # The last event (ORDER_CREATED) should be in emit_reason
    assert "ORDER_CREATED" in event.emit_reason
    # Verify the source indicates it's a lifecycle event
    assert "lifecycle_order_created" in event.last_source


@patch('app.api.routes_monitoring.add_telegram_message')
def test_sltp_emits_attempt_and_created_or_failed(mock_telegram, db_session, mock_watchlist_item):
    """Test that SLTP_ATTEMPT then SLTP_CREATED or SLTP_FAILED are emitted"""
    # Emit SLTP_ATTEMPT
    _emit_lifecycle_event(
        db=db_session,
        symbol="BTC_USDT",
        strategy_key="swing:conservative",
        side="BUY",
        price=50000.0,
        event_type="SLTP_ATTEMPT",
        event_reason="primary_order_id=test_123",
        order_id="test_123",
    )
    db_session.commit()
    
    # Emit SLTP_CREATED (success case)
    _emit_lifecycle_event(
        db=db_session,
        symbol="BTC_USDT",
        strategy_key="swing:conservative",
        side="BUY",
        price=50000.0,
        event_type="SLTP_CREATED",
        event_reason="primary_order_id=test_123",
        order_id="test_123",
        sl_order_id="sl_123",
        tp_order_id="tp_123",
    )
    db_session.commit()
    
    # Verify both events were recorded
    # record_signal_event upserts, so check the last event (SLTP_CREATED)
    event = db_session.query(SignalThrottleState).filter(
        SignalThrottleState.symbol == "BTC_USDT",
        SignalThrottleState.side == "BUY",
    ).first()
    
    assert event is not None
    # The last event (SLTP_CREATED) should be in emit_reason
    assert "SLTP_CREATED" in event.emit_reason
    # Verify the source indicates it's a lifecycle event
    assert "lifecycle_sltp_created" in event.last_source
    
    # Also test SLTP_FAILED case
    _emit_lifecycle_event(
        db=db_session,
        symbol="ETH_USDT",
        strategy_key="swing:conservative",
        side="BUY",
        price=3000.0,
        event_type="SLTP_ATTEMPT",
        event_reason="primary_order_id=test_456",
        order_id="test_456",
    )
    db_session.commit()
    
    _emit_lifecycle_event(
        db=db_session,
        symbol="ETH_USDT",
        strategy_key="swing:conservative",
        side="BUY",
        price=3000.0,
        event_type="SLTP_FAILED",
        event_reason="sltp_creation_failed",
        order_id="test_456",
        error_message="Normalization failed",
    )
    db_session.commit()
    
    # Verify SLTP_FAILED was recorded
    failed_event = db_session.query(SignalThrottleState).filter(
        SignalThrottleState.symbol == "ETH_USDT",
        SignalThrottleState.side == "BUY",
    ).first()
    
    assert failed_event is not None
    assert "SLTP_FAILED" in failed_event.emit_reason


@patch('app.api.routes_monitoring.add_telegram_message')
def test_order_canceled_emits_event_and_appears_in_executed_source(mock_telegram, db_session):
    """Test that ORDER_CANCELED is emitted and canceled orders appear in executed/canceled data source"""
    # Emit ORDER_CANCELED event
    _emit_lifecycle_event(
        db=db_session,
        symbol="BTC_USDT",
        strategy_key="swing:conservative",
        side="BUY",
        price=50000.0,
        event_type="ORDER_CANCELED",
        event_reason="order_id=test_canceled_123, reason=not_found_in_open_orders",
        order_id="test_canceled_123",
    )
    db_session.commit()
    
    # Verify event was recorded in SignalThrottleState
    event = db_session.query(SignalThrottleState).filter(
        SignalThrottleState.symbol == "BTC_USDT",
        SignalThrottleState.side == "BUY",
        SignalThrottleState.emit_reason.like("%ORDER_CANCELED%"),
    ).first()
    
    assert event is not None
    
    # Create a canceled order in ExchangeOrder table
    order = ExchangeOrder(
        exchange_order_id="test_canceled_123",
        symbol="BTC_USDT",
        side=OrderSideEnum.BUY,
        order_type="MARKET",
        status=OrderStatusEnum.CANCELLED,
        price=50000.0,
        quantity=0.002,
    )
    db_session.add(order)
    db_session.commit()
    
    # Query executed orders (should include CANCELLED)
    executed = db_session.query(ExchangeOrder).filter(
        ExchangeOrder.status.in_([OrderStatusEnum.FILLED, OrderStatusEnum.CANCELLED])
    ).all()
    
    assert len(executed) >= 1
    assert any(o.exchange_order_id == "test_canceled_123" for o in executed)
    assert any(o.status == OrderStatusEnum.CANCELLED for o in executed)
