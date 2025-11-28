#!/usr/bin/env python3
"""Check for signals sent in the last 5 minutes"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import get_db
from app.models.telegram_message import TelegramMessage
from app.models.signal_throttle import SignalThrottleState
from datetime import datetime, timezone, timedelta
from sqlalchemy import desc

def check_recent_signals():
    db = next(get_db())
    five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
    
    print(f"Checking for signals/alerts sent in the last 5 minutes (since {five_min_ago})...\n")
    
    # Check telegram messages (sent alerts)
    recent_alerts = db.query(TelegramMessage).filter(
        TelegramMessage.timestamp >= five_min_ago,
        TelegramMessage.blocked == False
    ).order_by(desc(TelegramMessage.timestamp)).limit(20).all()
    
    print(f"📨 Telegram Messages (sent alerts): {len(recent_alerts)}")
    for alert in recent_alerts:
        symbol_str = alert.symbol if alert.symbol else "N/A"
        msg_preview = (alert.message[:80] + "...") if alert.message and len(alert.message) > 80 else (alert.message or "")
        status = alert.throttle_status or "N/A"
        print(f"  {alert.timestamp} - {symbol_str} [{status}]: {msg_preview}")
    
    print()
    
    # Check signal throttle states (recent signal events)
    recent_states = db.query(SignalThrottleState).filter(
        SignalThrottleState.last_time >= five_min_ago
    ).order_by(desc(SignalThrottleState.last_time)).limit(20).all()
    
    print(f"📊 Signal Throttle States (recent signal events): {len(recent_states)}")
    for state in recent_states:
        print(f"  {state.last_time} - {state.symbol} {state.side}: price=${state.last_price}, source={state.last_source}")
    
    total = len(recent_alerts) + len(recent_states)
    print(f"\n✅ Total: {total} signal/alert events in last 5 minutes")

if __name__ == "__main__":
    check_recent_signals()

