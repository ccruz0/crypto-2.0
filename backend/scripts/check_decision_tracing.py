#!/usr/bin/env python3
"""
Diagnostic script to check if decision tracing is working correctly.

This script:
1. Checks if the database migration has been run (new columns exist)
2. Checks if messages with decision reasons are being saved
3. Shows recent blocked messages with decision tracing fields
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine
from sqlalchemy import text, inspect
from app.models.telegram_message import TelegramMessage
from datetime import datetime, timedelta

def check_migration_status():
    """Check if the migration has been run by verifying columns exist"""
    print("=" * 80)
    print("1. CHECKING DATABASE MIGRATION STATUS")
    print("=" * 80)
    
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('telegram_messages')]
    
    required_columns = [
        'decision_type',
        'reason_code',
        'reason_message',
        'context_json',
        'exchange_error_snippet',
        'correlation_id'
    ]
    
    missing_columns = [col for col in required_columns if col not in columns]
    
    if missing_columns:
        print(f"❌ MIGRATION NOT RUN: Missing columns: {', '.join(missing_columns)}")
        print(f"\n⚠️  ACTION REQUIRED: Run the migration script:")
        print(f"   psql -U trader -d atp -f backend/migrations/add_decision_tracing_fields.sql")
        print(f"   OR via Docker:")
        print(f"   docker compose --profile aws exec -T db psql -U trader -d atp -f /path/to/add_decision_tracing_fields.sql")
        return False
    else:
        print(f"✅ MIGRATION COMPLETE: All required columns exist")
        print(f"   Found columns: {', '.join(required_columns)}")
        return True

def check_recent_messages():
    """Check recent blocked messages and their decision tracing fields"""
    print("\n" + "=" * 80)
    print("2. CHECKING RECENT BLOCKED MESSAGES")
    print("=" * 80)
    
    db = SessionLocal()
    try:
        one_day_ago = datetime.now() - timedelta(days=1)
        
        # Get recent blocked messages
        blocked_messages = db.query(TelegramMessage).filter(
            TelegramMessage.blocked.is_(True),
            TelegramMessage.timestamp >= one_day_ago
        ).order_by(TelegramMessage.timestamp.desc()).limit(20).all()
        
        print(f"\nFound {len(blocked_messages)} blocked messages in the last 24 hours:\n")
        
        if not blocked_messages:
            print("⚠️  No blocked messages found in the last 24 hours.")
            print("   This could mean:")
            print("   - No alerts have been blocked yet")
            print("   - Alerts are being sent but not marked as blocked")
            print("   - _emit_lifecycle_event is not being called for skip/fail cases")
            return
        
        for i, msg in enumerate(blocked_messages, 1):
            print(f"\n--- Message {i} ---")
            print(f"Timestamp: {msg.timestamp}")
            print(f"Symbol: {msg.symbol}")
            print(f"Blocked: {msg.blocked}")
            print(f"Order Skipped: {msg.order_skipped}")
            print(f"Decision Type: {msg.decision_type or 'NULL'}")
            print(f"Reason Code: {msg.reason_code or 'NULL'}")
            print(f"Reason Message: {msg.reason_message or 'NULL'}")
            print(f"Context JSON: {msg.context_json or 'NULL'}")
            print(f"Exchange Error: {msg.exchange_error_snippet or 'NULL'}")
            print(f"Correlation ID: {msg.correlation_id or 'NULL'}")
            print(f"Message Preview: {msg.message[:100]}...")
            
            if not msg.decision_type:
                print("⚠️  WARNING: This message has blocked=True but no decision_type!")
                print("   This suggests the decision tracing fields are not being populated.")
    
    finally:
        db.close()

def check_recent_sent_messages():
    """Check recent sent messages (blocked=False) to see if they should be blocked"""
    print("\n" + "=" * 80)
    print("3. CHECKING RECENT SENT MESSAGES (blocked=False)")
    print("=" * 80)
    
    db = SessionLocal()
    try:
        one_day_ago = datetime.now() - timedelta(days=1)
        
        # Get recent sent messages
        sent_messages = db.query(TelegramMessage).filter(
            TelegramMessage.blocked.is_(False),
            TelegramMessage.timestamp >= one_day_ago
        ).order_by(TelegramMessage.timestamp.desc()).limit(10).all()
        
        print(f"\nFound {len(sent_messages)} sent messages (blocked=False) in the last 24 hours:\n")
        
        if not sent_messages:
            print("ℹ️  No sent messages found in the last 24 hours.")
            return
        
        for i, msg in enumerate(sent_messages, 1):
            print(f"\n--- Sent Message {i} ---")
            print(f"Timestamp: {msg.timestamp}")
            print(f"Symbol: {msg.symbol}")
            print(f"Message Preview: {msg.message[:100]}...")
            print(f"Note: These are successfully sent alerts. If buy orders were skipped/failed,")
            print(f"      there should be a corresponding blocked=True entry with decision_type.")
    
    finally:
        db.close()

def check_message_counts():
    """Check overall message statistics"""
    print("\n" + "=" * 80)
    print("4. MESSAGE STATISTICS")
    print("=" * 80)
    
    db = SessionLocal()
    try:
        one_day_ago = datetime.now() - timedelta(days=1)
        one_week_ago = datetime.now() - timedelta(days=7)
        
        total_blocked = db.query(TelegramMessage).filter(
            TelegramMessage.blocked.is_(True)
        ).count()
        
        total_sent = db.query(TelegramMessage).filter(
            TelegramMessage.blocked.is_(False)
        ).count()
        
        blocked_today = db.query(TelegramMessage).filter(
            TelegramMessage.blocked.is_(True),
            TelegramMessage.timestamp >= one_day_ago
        ).count()
        
        sent_today = db.query(TelegramMessage).filter(
            TelegramMessage.blocked.is_(False),
            TelegramMessage.timestamp >= one_day_ago
        ).count()
        
        with_decision_type = db.query(TelegramMessage).filter(
            TelegramMessage.decision_type.isnot(None)
        ).count()
        
        with_reason_code = db.query(TelegramMessage).filter(
            TelegramMessage.reason_code.isnot(None)
        ).count()
        
        print(f"\nTotal Messages (all time):")
        print(f"  Blocked: {total_blocked}")
        print(f"  Sent: {total_sent}")
        print(f"\nMessages (last 24 hours):")
        print(f"  Blocked: {blocked_today}")
        print(f"  Sent: {sent_today}")
        print(f"\nDecision Tracing:")
        print(f"  Messages with decision_type: {with_decision_type}")
        print(f"  Messages with reason_code: {with_reason_code}")
        
        if sent_today > 0 and blocked_today == 0:
            print(f"\n⚠️  WARNING: {sent_today} messages were sent today, but 0 were blocked.")
            print(f"   This suggests that alerts are being sent, but buy order skip/fail")
            print(f"   events are not being recorded as blocked=True entries.")
    
    finally:
        db.close()

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("DECISION TRACING DIAGNOSTIC SCRIPT")
    print("=" * 80)
    
    migration_ok = check_migration_status()
    
    if migration_ok:
        check_recent_messages()
        check_recent_sent_messages()
        check_message_counts()
    else:
        print("\n⚠️  Cannot check messages until migration is run.")
    
    print("\n" + "=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)

