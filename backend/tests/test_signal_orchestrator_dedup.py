"""
Regression test for idempotency across time windows.

Tests that signal_id-based dedup works forever (no timestamp bucket).
"""
import pytest
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.services.signal_order_orchestrator import create_order_intent, compute_idempotency_key
from app.models.order_intent import OrderIntent

# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_dedup.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def setup_module(module):
    Base.metadata.create_all(bind=engine)

def teardown_module(module):
    Base.metadata.drop_all(bind=engine)

def get_test_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_idempotency_key_no_timestamp():
    """Test that signal_id-based keys don't include timestamp"""
    key1 = compute_idempotency_key(signal_id=123, symbol="BTC_USDT", side="BUY", message_content="test")
    key2 = compute_idempotency_key(signal_id=123, symbol="BTC_USDT", side="BUY", message_content="test")
    assert key1 == key2, "Same inputs should produce same key"
    assert key1 == "signal:123:side:BUY", "Signal_id-based key should be signal:{signal_id}:side:{side}"
    
    key3 = compute_idempotency_key(signal_id=456, symbol="BTC_USDT", side="BUY", message_content="test")
    assert key1 != key3, "Different signal_id should produce different key"


def test_idempotency_across_time_window():
    """Test that signal_id-based dedup works across time boundaries (no timestamp bucket)"""
    db = next(get_test_db())
    
    test_signal_id = 999888
    symbol = "TEST_USDT"
    side = "BUY"
    message = "Test message for time window"
    
    # Clean up any existing test data
    db.query(OrderIntent).filter(OrderIntent.signal_id == test_signal_id).delete()
    db.commit()
    
    # Create first intent
    order_intent1, status1 = create_order_intent(
        db=db,
        signal_id=test_signal_id,
        symbol=symbol,
        side=side,
        message_content=message
    )
    assert status1 == "PENDING"
    assert order_intent1 is not None
    first_intent_id = order_intent1.id
    
    # Wait >60 seconds to cross timestamp bucket boundary
    time.sleep(65)
    
    # Try to create duplicate after >60s (should still dedup because signal_id is used)
    order_intent2, status2 = create_order_intent(
        db=db,
        signal_id=test_signal_id,
        symbol=symbol,
        side=side,
        message_content=message
    )
    assert status2 == "DEDUP_SKIPPED", f"Expected DEDUP_SKIPPED but got {status2}"
    assert order_intent2 is None
    
    # Verify only one order_intent exists
    intents = db.query(OrderIntent).filter(OrderIntent.signal_id == test_signal_id).all()
    assert len(intents) == 1, f"Expected 1 order_intent but found {len(intents)}"
    assert intents[0].id == first_intent_id, "The existing intent should be the first one"
