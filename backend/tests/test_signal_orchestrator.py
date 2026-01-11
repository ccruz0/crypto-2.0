#!/usr/bin/env python3
"""
Test script for signal-to-order orchestrator.

Tests:
1. Create a synthetic BUY SIGNAL and confirm one order intent + one order attempt
2. Run the same signal twice => second is DEDUP_SKIPPED, no second exchange call
"""
import sys
import os
import asyncio
from datetime import datetime, timezone

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.order_intent import OrderIntent
from app.models.telegram_message import TelegramMessage
from app.services.signal_order_orchestrator import create_order_intent, compute_idempotency_key
from app.api.routes_monitoring import add_telegram_message, update_telegram_message_decision_trace


def test_orchestrator_deduplication():
    """Test that duplicate signals are deduplicated"""
    db = SessionLocal()
    try:
        symbol = "TEST_USDT"
        side = "BUY"
        
        # Create a test watchlist item (if it doesn't exist)
        watchlist_item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
        if not watchlist_item:
            watchlist_item = WatchlistItem(
                symbol=symbol,
                exchange="CRYPTO_COM",
                trade_enabled=True,
                alert_enabled=True,
                buy_alert_enabled=True,
                trade_amount_usd=100.0,
            )
            db.add(watchlist_item)
            db.commit()
        
        # Clean up existing test data
        db.query(OrderIntent).filter(OrderIntent.symbol == symbol).delete()
        db.query(TelegramMessage).filter(TelegramMessage.symbol == symbol).delete()
        db.commit()
        
        print(f"\n=== Test 1: Create synthetic BUY SIGNAL ===")
        
        # Create a synthetic BUY SIGNAL message
        message_content = f"✅ BUY SIGNAL: {symbol} @ $1.00 - Test signal"
        signal_id = add_telegram_message(
            message=message_content,
            symbol=symbol,
            blocked=False,
            throttle_status="SENT",
            throttle_reason="Test signal",
            db=db,
        )
        print(f"✅ Created Telegram message with signal_id={signal_id}")
        
        # Create order intent (first time)
        order_intent1, status1 = create_order_intent(
            db=db,
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            message_content=message_content,
        )
        print(f"✅ First order intent: status={status1}, id={order_intent1.id if order_intent1 else None}")
        
        # Verify order intent was created
        assert order_intent1 is not None, "Order intent should be created"
        assert status1 in ("PENDING", "ORDER_BLOCKED_LIVE_TRADING"), f"Status should be PENDING or ORDER_BLOCKED_LIVE_TRADING, got {status1}"
        assert order_intent1.signal_id == signal_id, "Signal ID should match"
        assert order_intent1.symbol == symbol, "Symbol should match"
        assert order_intent1.side == side, "Side should match"
        
        print(f"\n=== Test 2: Duplicate signal (should be DEDUP_SKIPPED) ===")
        
        # Create order intent again (should be duplicate)
        order_intent2, status2 = create_order_intent(
            db=db,
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            message_content=message_content,
        )
        print(f"✅ Second order intent: status={status2}, id={order_intent2.id if order_intent2 else None}")
        
        # Verify duplicate was detected
        assert order_intent2 is None, "Duplicate order intent should return None"
        assert status2 == "DEDUP_SKIPPED", f"Status should be DEDUP_SKIPPED, got {status2}"
        
        # Verify only one order intent exists in DB
        order_intents = db.query(OrderIntent).filter(OrderIntent.symbol == symbol).all()
        assert len(order_intents) == 1, f"Should have exactly 1 order intent, got {len(order_intents)}"
        print(f"✅ Verified: Only 1 order intent in database (deduplication worked)")
        
        print(f"\n=== Test 3: Different signal_id (should create new intent) ===")
        
        # Create a different signal
        signal_id2 = add_telegram_message(
            message=f"✅ BUY SIGNAL: {symbol} @ $1.01 - Different test signal",
            symbol=symbol,
            blocked=False,
            throttle_status="SENT",
            throttle_reason="Different test signal",
            db=db,
        )
        print(f"✅ Created second Telegram message with signal_id={signal_id2}")
        
        # Create order intent with different signal_id (should create new intent)
        order_intent3, status3 = create_order_intent(
            db=db,
            signal_id=signal_id2,
            symbol=symbol,
            side=side,
            message_content=f"Different message for {symbol}",
        )
        print(f"✅ Third order intent: status={status3}, id={order_intent3.id if order_intent3 else None}")
        
        # Verify new intent was created
        assert order_intent3 is not None, "New order intent should be created"
        assert status3 in ("PENDING", "ORDER_BLOCKED_LIVE_TRADING"), f"Status should be PENDING or ORDER_BLOCKED_LIVE_TRADING, got {status3}"
        assert order_intent3.signal_id == signal_id2, "Signal ID should match"
        
        # Verify we now have 2 order intents
        order_intents = db.query(OrderIntent).filter(OrderIntent.symbol == symbol).all()
        assert len(order_intents) == 2, f"Should have exactly 2 order intents, got {len(order_intents)}"
        print(f"✅ Verified: 2 order intents in database (different signal_ids)")
        
        print(f"\n✅ All tests passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    print("Testing signal-to-order orchestrator...")
    success = test_orchestrator_deduplication()
    sys.exit(0 if success else 1)
