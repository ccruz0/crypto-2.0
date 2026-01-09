#!/usr/bin/env python3
"""
Script to manually trigger an alert and monitor decision tracing.

Usage:
    python trigger_manual_alert.py SYMBOL [SIDE]

Example:
    python trigger_manual_alert.py ALGO_USDT BUY
    python trigger_manual_alert.py ETH_USDT SELL
"""

import os
import sys
import time
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Database connection
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://trader:traderpass@localhost:5432/atp"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def set_force_next_signal(db, symbol: str, strategy_key: str, side: str, enabled: bool = True):
    """Set force_next_signal flag to bypass throttle."""
    from app.models.signal_throttle import SignalThrottleState
    
    symbol = symbol.upper()
    side = side.upper()
    
    # Get or create throttle state
    throttle_state = db.query(SignalThrottleState).filter(
        SignalThrottleState.symbol == symbol,
        SignalThrottleState.strategy_key == strategy_key,
        SignalThrottleState.side == side
    ).first()
    
    if not throttle_state:
        # Create new throttle state
        throttle_state = SignalThrottleState(
            symbol=symbol,
            strategy_key=strategy_key,
            side=side,
            last_time=datetime.now(timezone.utc),
            force_next_signal=enabled
        )
        db.add(throttle_state)
    else:
        throttle_state.force_next_signal = enabled
    
    db.commit()
    return throttle_state


def get_strategy_key(db, symbol: str):
    """Get strategy key for a symbol."""
    from app.models.watchlist import WatchlistItem
    from app.services.strategy_profiles import resolve_strategy_profile
    from app.services.signal_throttle import build_strategy_key
    
    watchlist_item = db.query(WatchlistItem).filter(
        WatchlistItem.symbol == symbol.upper()
    ).first()
    
    if not watchlist_item:
        return None
    
    strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
    return build_strategy_key(strategy_type, risk_approach)


def monitor_alert(db, symbol: str, start_time: datetime):
    """Monitor for new alerts and decision tracing."""
    print(f"\n🔍 Monitoring for alerts and decision tracing...")
    print(f"   Symbol: {symbol}")
    print(f"   Start time: {start_time}")
    print("=" * 80)
    
    max_wait = 120  # Wait up to 2 minutes
    check_interval = 5  # Check every 5 seconds
    elapsed = 0
    
    while elapsed < max_wait:
        # Check for new alerts
        query = text("""
            SELECT 
                id,
                symbol,
                LEFT(message, 100) as msg_preview,
                blocked,
                order_skipped,
                decision_type,
                reason_code,
                LEFT(reason_message, 80) as reason_preview,
                context_json,
                exchange_error_snippet,
                timestamp
            FROM telegram_messages
            WHERE symbol = :symbol
                AND timestamp >= :start_time
                AND (
                    message LIKE '%BUY SIGNAL%' 
                    OR message LIKE '%SELL SIGNAL%'
                    OR message LIKE '%TRADE BLOCKED%'
                    OR message LIKE '%ORDER BLOCKED%'
                )
            ORDER BY timestamp DESC
            LIMIT 10
        """)
        
        result = db.execute(query, {"symbol": symbol.upper(), "start_time": start_time})
        alerts = [dict(row._mapping) for row in result]
        
        if alerts:
            print(f"\n✅ Found {len(alerts)} alert(s):")
            for alert in alerts:
                print(f"\n  Alert ID: {alert['id']}")
                print(f"  Time: {alert['timestamp']}")
                print(f"  Message: {alert['msg_preview']}")
                print(f"  Blocked: {alert['blocked']}")
                print(f"  Order Skipped: {alert['order_skipped']}")
                print(f"  Decision Type: {alert['decision_type'] or 'N/A'}")
                print(f"  Reason Code: {alert['reason_code'] or 'N/A'}")
                print(f"  Reason Message: {alert['reason_preview'] or 'N/A'}")
                if alert.get('context_json'):
                    print(f"  Context: {alert['context_json']}")
                if alert.get('exchange_error_snippet'):
                    print(f"  Exchange Error: {alert['exchange_error_snippet']}")
            
            # Check if order was created
            order_query = text("""
                SELECT 
                    exchange_order_id,
                    side,
                    status,
                    price,
                    quantity,
                    created_at
                FROM exchange_orders
                WHERE symbol = :symbol
                    AND created_at >= :start_time
                    AND side IN ('BUY', 'SELL')
                ORDER BY created_at DESC
                LIMIT 1
            """)
            
            order_result = db.execute(order_query, {"symbol": symbol.upper(), "start_time": start_time})
            order = order_result.first()
            
            if order:
                order_dict = dict(order._mapping)
                print(f"\n  ✅ ORDER CREATED:")
                print(f"     Order ID: {order_dict['exchange_order_id']}")
                print(f"     Side: {order_dict['side']}")
                print(f"     Status: {order_dict['status']}")
                print(f"     Price: {order_dict['price']}")
                print(f"     Quantity: {order_dict['quantity']}")
            else:
                print(f"\n  ❌ NO ORDER CREATED")
                if not any(a.get('decision_type') for a in alerts):
                    print(f"  ⚠️  WARNING: No decision tracing found!")
                else:
                    print(f"  ✅ Decision tracing found: {alerts[0].get('reason_code')}")
            
            return alerts
        
        time.sleep(check_interval)
        elapsed += check_interval
        if elapsed % 15 == 0:
            print(f"  ⏳ Still waiting... ({elapsed}s elapsed)")
    
    print(f"\n⏱️  Timeout: No alerts found within {max_wait} seconds")
    return []


def main():
    if len(sys.argv) < 2:
        print("Usage: python trigger_manual_alert.py SYMBOL [SIDE]")
        print("Example: python trigger_manual_alert.py ALGO_USDT BUY")
        sys.exit(1)
    
    symbol = sys.argv[1].upper()
    side = sys.argv[2].upper() if len(sys.argv) > 2 else "BUY"
    
    print("=" * 80)
    print("🚀 Manual Alert Trigger")
    print("=" * 80)
    print(f"Symbol: {symbol}")
    print(f"Side: {side}")
    print()
    
    db = SessionLocal()
    start_time = datetime.now(timezone.utc)
    
    try:
        # Get strategy key
        strategy_key = get_strategy_key(db, symbol)
        if not strategy_key:
            print(f"❌ Error: Symbol {symbol} not found in watchlist")
            sys.exit(1)
        
        print(f"Strategy Key: {strategy_key}")
        
        # Set force_next_signal
        print(f"\n⚡ Setting force_next_signal=True for {symbol} {side}...")
        throttle_state = set_force_next_signal(db, symbol, strategy_key, side, enabled=True)
        print(f"✅ force_next_signal set to {throttle_state.force_next_signal}")
        
        print(f"\n⏳ Waiting for next monitoring cycle to trigger alert...")
        print(f"   (The alert will be triggered automatically in the next cycle)")
        print(f"   Monitoring will start in 10 seconds...")
        time.sleep(10)
        
        # Monitor for alerts
        alerts = monitor_alert(db, symbol, start_time)
        
        if alerts:
            print(f"\n✅ Alert triggered successfully!")
            print(f"\n📊 Summary:")
            print(f"   Total alerts: {len(alerts)}")
            print(f"   With decision tracing: {sum(1 for a in alerts if a.get('decision_type'))}")
            print(f"   Orders created: {sum(1 for a in alerts if not a.get('blocked') and not a.get('order_skipped'))}")
        else:
            print(f"\n⚠️  No alerts found. Possible reasons:")
            print(f"   1. Monitoring cycle hasn't run yet (wait a bit longer)")
            print(f"   2. Signal conditions not met (RSI, MA, etc.)")
            print(f"   3. alert_enabled=False for this symbol")
        
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

