#!/usr/bin/env python3
"""
Monitor alerts and detect why orders are not executed.
This script monitors the database for new alerts and checks if orders were created.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.database import create_db_session, exit_2_if_missing_schema_tables


def get_recent_alerts(db, minutes: int = 5) -> list:
    """Get recent alerts from telegram_messages."""
    # Bound cutoff (portable SQLite + Postgres); INTERVAL + :bind inside literal never worked here.
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    query = text("""
        SELECT 
            id,
            symbol,
            message,
            blocked,
            order_skipped,
            decision_type,
            reason_code,
            reason_message,
            context_json,
            exchange_error_snippet,
            timestamp
        FROM telegram_messages
        WHERE timestamp >= :cutoff
            AND (
                message LIKE '%BUY SIGNAL%' 
                OR message LIKE '%SELL SIGNAL%'
                OR message LIKE '%BLOCKED%'
                OR message LIKE '%ORDER%'
            )
        ORDER BY timestamp DESC
        LIMIT 50
    """)
    
    result = db.execute(query, {"cutoff": cutoff})
    return [dict(row._mapping) for row in result]


def check_order_created(db, symbol: str, alert_time: datetime) -> Optional[Dict[str, Any]]:
    """Check if an order was created for this symbol after the alert."""
    query = text("""
        SELECT 
            exchange_order_id,
            symbol,
            side,
            status,
            price,
            quantity,
            created_at,
            exchange_create_time
        FROM exchange_orders
        WHERE symbol = :symbol
            AND created_at >= :alert_time
            AND side IN ('BUY', 'SELL')
        ORDER BY created_at DESC
        LIMIT 1
    """)
    
    result = db.execute(query, {"symbol": symbol, "alert_time": alert_time})
    row = result.first()
    if row:
        return dict(row._mapping)
    return None


def analyze_alert(db, alert: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze an alert to determine why order was not executed."""
    symbol = alert['symbol']
    alert_time = alert['timestamp']
    
    # Check if order was created
    order = check_order_created(db, symbol, alert_time)
    
    result = {
        "alert_id": alert['id'],
        "symbol": symbol,
        "alert_time": alert_time,
        "message_preview": alert['message'][:100] if alert['message'] else "",
        "order_created": order is not None,
        "order_details": order,
        "blocked": alert.get('blocked', False),
        "order_skipped": alert.get('order_skipped', False),
        "decision_type": alert.get('decision_type'),
        "reason_code": alert.get('reason_code'),
        "reason_message": alert.get('reason_message'),
        "context_json": alert.get('context_json'),
        "exchange_error": alert.get('exchange_error_snippet'),
    }
    
    # Determine why order was not executed
    if order:
        result["status"] = "✅ ORDER CREATED"
        result["why_not_executed"] = None
    elif alert.get('blocked') or alert.get('order_skipped'):
        if alert.get('decision_type') and alert.get('reason_code'):
            result["status"] = f"🚫 BLOCKED: {alert.get('reason_code')}"
            result["why_not_executed"] = {
                "decision_type": alert.get('decision_type'),
                "reason_code": alert.get('reason_code'),
                "reason_message": alert.get('reason_message'),
                "context": alert.get('context_json'),
            }
        else:
            result["status"] = "⚠️ BLOCKED (no decision tracing)"
            result["why_not_executed"] = "Alert was blocked but no decision tracing found"
    else:
        result["status"] = "❓ UNKNOWN"
        result["why_not_executed"] = "Alert sent but no order created and no blocking reason found"
    
    return result


def main():
    """Main monitoring loop."""
    print("🔍 Starting alert monitoring...")
    print(f"Monitoring alerts from the last 5 minutes")
    print("=" * 80)
    
    db = create_db_session()
    last_checked_ids = set()
    
    try:
        while True:
            try:
                alerts = get_recent_alerts(db, minutes=5)
            except OperationalError as e:
                exit_2_if_missing_schema_tables(
                    e,
                    table_names=("telegram_messages",),
                    stderr_message=(
                        "Connected to the app database, but table `telegram_messages` is missing. "
                        "Run migrations or set DATABASE_URL to a migrated instance."
                    ),
                )
            
            for alert in alerts:
                alert_id = alert['id']
                
                # Skip if we already analyzed this alert
                if alert_id in last_checked_ids:
                    continue
                
                # Only analyze BUY/SELL signals
                message = alert.get('message', '')
                if 'BUY SIGNAL' not in message and 'SELL SIGNAL' not in message:
                    continue
                
                last_checked_ids.add(alert_id)
                
                # Analyze the alert
                analysis = analyze_alert(db, alert)
                
                # Print results
                print(f"\n{'='*80}")
                print(f"🚨 NEW ALERT DETECTED")
                print(f"{'='*80}")
                print(f"Alert ID: {analysis['alert_id']}")
                print(f"Symbol: {analysis['symbol']}")
                print(f"Time: {analysis['alert_time']}")
                print(f"Status: {analysis['status']}")
                print(f"Message: {analysis['message_preview']}")
                
                if analysis['order_created']:
                    order = analysis['order_details']
                    print(f"\n✅ ORDER CREATED:")
                    print(f"   Order ID: {order.get('exchange_order_id')}")
                    print(f"   Side: {order.get('side')}")
                    print(f"   Status: {order.get('status')}")
                    print(f"   Price: {order.get('price')}")
                    print(f"   Quantity: {order.get('quantity')}")
                elif analysis['why_not_executed']:
                    print(f"\n🚫 ORDER NOT EXECUTED:")
                    if isinstance(analysis['why_not_executed'], dict):
                        print(f"   Decision Type: {analysis['why_not_executed'].get('decision_type')}")
                        print(f"   Reason Code: {analysis['why_not_executed'].get('reason_code')}")
                        print(f"   Reason Message: {analysis['why_not_executed'].get('reason_message')}")
                        if analysis['why_not_executed'].get('context'):
                            print(f"   Context: {analysis['why_not_executed'].get('context')}")
                    else:
                        print(f"   {analysis['why_not_executed']}")
                else:
                    print(f"\n❓ UNKNOWN REASON - No order created and no blocking reason found")
                
                print(f"{'='*80}\n")
            
            # Wait before next check
            time.sleep(10)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()

