#!/usr/bin/env python3
"""
Diagnostic script to check why signal throttle is not sending signals.

This script checks:
1. If signal monitor service is running
2. If there are watchlist items with alert_enabled=True
3. If signals are being detected but throttled
4. Recent throttle state from database
5. Recent logs
"""

import sys
import os
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.signal_throttle import SignalThrottleState
from app.services.signal_monitor import signal_monitor_service
import json

def check_signal_monitor_status():
    """Check if signal monitor service is running"""
    print("\n" + "="*60)
    print("1. SIGNAL MONITOR STATUS")
    print("="*60)
    
    is_running = signal_monitor_service.is_running
    print(f"   is_running: {is_running}")
    
    # Check status file
    status_file = signal_monitor_service.status_file_path
    if status_file.exists():
        try:
            status_data = json.loads(status_file.read_text())
            print(f"   Status file exists: {status_file}")
            print(f"   State: {status_data.get('state', 'unknown')}")
            print(f"   Last run at: {status_data.get('last_run_at', 'never')}")
            print(f"   Updated at: {status_data.get('updated_at', 'never')}")
            
            # Check if stale
            updated_at_str = status_data.get('updated_at')
            if updated_at_str:
                try:
                    updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    age = now - updated_at
                    print(f"   Age: {age}")
                    if age > timedelta(minutes=2):
                        print(f"   ⚠️  WARNING: Status is stale (older than 2 minutes)")
                except Exception as e:
                    print(f"   ⚠️  Could not parse updated_at: {e}")
        except Exception as e:
            print(f"   ⚠️  Error reading status file: {e}")
    else:
        print(f"   ⚠️  Status file not found: {status_file}")
    
    return is_running

def check_watchlist_items(db: Session):
    """Check watchlist items with alert_enabled=True"""
    print("\n" + "="*60)
    print("2. WATCHLIST ITEMS WITH alert_enabled=True")
    print("="*60)
    
    try:
        # Try with is_deleted filter first
        try:
            items = db.query(WatchlistItem).filter(
                WatchlistItem.alert_enabled == True,
                WatchlistItem.is_deleted == False
            ).all()
        except Exception:
            # Fallback if is_deleted doesn't exist
            items = db.query(WatchlistItem).filter(
                WatchlistItem.alert_enabled == True
            ).all()
        
        print(f"   Found {len(items)} items with alert_enabled=True")
        
        if len(items) == 0:
            print("   ⚠️  WARNING: No watchlist items with alert_enabled=True!")
            print("   This means signal monitor has nothing to monitor.")
            return []
        
        print("\n   Items:")
        for item in items[:10]:  # Show first 10
            buy_alert = getattr(item, 'buy_alert_enabled', None)
            sell_alert = getattr(item, 'sell_alert_enabled', None)
            print(f"   - {item.symbol}: alert_enabled=True, buy_alert_enabled={buy_alert}, sell_alert_enabled={sell_alert}, trade_enabled={item.trade_enabled}")
        
        if len(items) > 10:
            print(f"   ... and {len(items) - 10} more")
        
        return items
    except Exception as e:
        print(f"   ❌ Error querying watchlist: {e}")
        return []

def check_recent_throttle_events(db: Session):
    """Check recent throttle events from database"""
    print("\n" + "="*60)
    print("3. RECENT THROTTLE EVENTS (from database)")
    print("="*60)
    
    try:
        # Get events from last 7 days
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        events = db.query(SignalThrottleState).filter(
            SignalThrottleState.last_time >= cutoff
        ).order_by(SignalThrottleState.last_time.desc()).limit(20).all()
        
        print(f"   Found {len(events)} events in last 7 days")
        
        if len(events) == 0:
            print("   ⚠️  WARNING: No throttle events in last 7 days!")
            print("   This suggests signals are not being detected or recorded.")
        
        now = datetime.now(timezone.utc)
        print("\n   Recent events:")
        for event in events[:10]:
            age = now - event.last_time if event.last_time else timedelta(0)
            age_str = f"{age.days}d {age.seconds//3600}h {(age.seconds%3600)//60}m"
            print(f"   - {event.symbol} {event.side}: {event.last_price} @ {event.last_time} ({age_str} ago)")
        
        # Group by symbol to see which ones are most active
        from collections import defaultdict
        by_symbol = defaultdict(list)
        for event in events:
            by_symbol[event.symbol].append(event)
        
        print(f"\n   Events by symbol (top 10):")
        sorted_symbols = sorted(by_symbol.items(), key=lambda x: len(x[1]), reverse=True)
        for symbol, symbol_events in sorted_symbols[:10]:
            latest = max(symbol_events, key=lambda e: e.last_time if e.last_time else datetime.min.replace(tzinfo=timezone.utc))
            age = now - latest.last_time if latest.last_time else timedelta(0)
            age_str = f"{age.days}d {age.seconds//3600}h {(age.seconds%3600)//60}m"
            print(f"   - {symbol}: {len(symbol_events)} events, latest {age_str} ago")
        
        return events
    except Exception as e:
        print(f"   ❌ Error querying throttle events: {e}")
        import traceback
        traceback.print_exc()
        return []

def check_signal_detection(db: Session, watchlist_items):
    """Check if signals are being detected for watchlist items"""
    print("\n" + "="*60)
    print("4. SIGNAL DETECTION CHECK")
    print("="*60)
    
    if not watchlist_items:
        print("   ⚠️  Skipping: No watchlist items to check")
        return
    
    print(f"   Checking {len(watchlist_items)} watchlist items...")
    print("   (This would require running signal calculations - see logs for actual detection)")
    print("   💡 Tip: Check backend logs for 'signal check' or 'BUY signal detected' messages")

def main():
    print("="*60)
    print("SIGNAL THROTTLE DIAGNOSTIC")
    print("="*60)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    
    db = SessionLocal()
    try:
        # Check 1: Signal monitor status
        is_running = check_signal_monitor_status()
        
        # Check 2: Watchlist items
        watchlist_items = check_watchlist_items(db)
        
        # Check 3: Recent throttle events
        throttle_events = check_recent_throttle_events(db)
        
        # Check 4: Signal detection
        check_signal_detection(db, watchlist_items)
        
        # Summary
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        
        issues = []
        if not is_running:
            issues.append("❌ Signal monitor is NOT running")
        if not watchlist_items:
            issues.append("❌ No watchlist items with alert_enabled=True")
        if not throttle_events:
            issues.append("❌ No throttle events in last 7 days")
        
        if issues:
            print("   ISSUES FOUND:")
            for issue in issues:
                print(f"   {issue}")
            print("\n   RECOMMENDATIONS:")
            if not is_running:
                print("   1. Start signal monitor service")
                print("      - Check if DEBUG_DISABLE_SIGNAL_MONITOR is False in main.py")
                print("      - Restart backend service")
            if not watchlist_items:
                print("   2. Enable alerts for watchlist items")
                print("      - Go to dashboard and enable alert_enabled for coins")
            if not throttle_events:
                print("   3. Check backend logs for signal detection")
                print("      - Look for 'signal check' or 'BUY signal detected' messages")
                print("      - Check if signals are being throttled (THROTTLED messages)")
        else:
            print("   ✅ All checks passed")
            print("   If signals still not sending, check:")
            print("   - Backend logs for throttle reasons")
            print("   - buy_alert_enabled/sell_alert_enabled flags")
            print("   - Throttle configuration (min_price_change_pct, min_interval_minutes)")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
