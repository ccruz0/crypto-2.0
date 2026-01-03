#!/usr/bin/env python3
"""
Monitor for new SELL orders and verify SL/TP creation
Runs continuously and checks every 30 seconds
"""
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add backend to path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum

def check_sell_orders():
    """Check for new SELL orders and their SL/TP status"""
    db = SessionLocal()
    
    try:
        # Check for SELL orders filled in the last 5 minutes
        last_5min = datetime.now(timezone.utc) - timedelta(minutes=5)
        
        recent_sell = db.query(ExchangeOrder).filter(
            ExchangeOrder.side == 'SELL',
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.exchange_update_time >= last_5min
        ).order_by(ExchangeOrder.exchange_update_time.desc()).all()
        
        if recent_sell:
            print(f"\n{'='*80}")
            print(f"🔔 NEW SELL ORDER(S) DETECTED - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"{'='*80}\n")
            
            for order in recent_sell:
                # Check SL/TP
                sl = db.query(ExchangeOrder).filter(
                    ExchangeOrder.parent_order_id == order.exchange_order_id,
                    ExchangeOrder.order_role == 'STOP_LOSS'
                ).count()
                
                tp = db.query(ExchangeOrder).filter(
                    ExchangeOrder.parent_order_id == order.exchange_order_id,
                    ExchangeOrder.order_role == 'TAKE_PROFIT'
                ).count()
                
                status = "✅" if (sl > 0 and tp > 0) else "❌"
                print(f"{status} {order.symbol} - Order: {order.exchange_order_id}")
                print(f"   Price: ${order.avg_price or order.price:.4f} | Qty: {order.quantity:.6f}")
                print(f"   SL: {sl} | TP: {tp}")
                
                if sl == 0 or tp == 0:
                    print(f"   ⚠️  MISSING SL/TP - Order may need manual creation")
                    print(f"   Run: python3 create_sl_tp_manual.py {order.exchange_order_id} --force")
                print()
        else:
            print(f"⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')} - No new SELL orders (checking every 30s)")
        
    finally:
        db.close()

if __name__ == "__main__":
    print("🔍 Monitoring for new SELL orders...")
    print("   Checking every 30 seconds")
    print("   Press Ctrl+C to stop\n")
    
    try:
        while True:
            check_sell_orders()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n\n👋 Monitoring stopped")





