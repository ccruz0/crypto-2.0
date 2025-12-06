#!/usr/bin/env python3
"""Check SOL_USDT watchlist configuration to see why orders were executed"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def check_sol_config():
    """Check SOL_USDT configuration"""
    db = SessionLocal()
    try:
        sol_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == "SOL_USDT",
            WatchlistItem.is_deleted == False
        ).first()
        
        if not sol_item:
            print("❌ SOL_USDT not found in watchlist")
            return
        
        print("=" * 60)
        print("SOL_USDT Watchlist Configuration")
        print("=" * 60)
        print(f"Symbol: {sol_item.symbol}")
        print(f"Exchange: {sol_item.exchange}")
        print(f"\n🔔 Alert Settings:")
        print(f"   alert_enabled: {sol_item.alert_enabled}")
        print(f"\n💰 Trading Settings:")
        print(f"   trade_enabled: {sol_item.trade_enabled}")
        print(f"   trade_amount_usd: ${sol_item.trade_amount_usd or 0:,.2f}")
        print(f"   trade_on_margin: {sol_item.trade_on_margin}")
        print(f"\n🛡️ SL/TP Settings:")
        print(f"   sl_tp_mode: {sol_item.sl_tp_mode}")
        print(f"   sl_percentage: {sol_item.sl_percentage or 'Not set'}")
        print(f"   tp_percentage: {sol_item.tp_percentage or 'Not set'}")
        print(f"   sl_price: ${sol_item.sl_price or 'Not set'}")
        print(f"   tp_price: ${sol_item.tp_price or 'Not set'}")
        print("=" * 60)
        
        # Determine why orders were executed
        print("\n📊 Analysis:")
        if sol_item.alert_enabled and sol_item.trade_enabled:
            print("✅ AUTOMATIC TRADING IS ENABLED")
            print("   → Signal Monitor Service will create BUY orders automatically")
            if sol_item.trade_amount_usd and sol_item.trade_amount_usd > 0:
                print(f"   → Order size: ${sol_item.trade_amount_usd:,.2f} per order")
            else:
                print("   ⚠️  WARNING: trade_amount_usd not set - orders may fail")
        elif sol_item.alert_enabled and not sol_item.trade_enabled:
            print("🔔 ALERTS ONLY (No Trading)")
            print("   → You'll get Telegram alerts but NO automatic orders")
        else:
            print("❌ ALERTS DISABLED")
            print("   → No alerts, no orders")
        
        print("\n💡 To disable automatic trading:")
        print("   1. Set 'Trade' to NO in Dashboard Watchlist")
        print("   2. Or set trade_enabled = false in database")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_sol_config()

