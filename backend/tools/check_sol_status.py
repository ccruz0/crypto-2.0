#!/usr/bin/env python3
"""
Script to check SOL_USDT status in watchlist and verify conditions for automatic order creation.
"""
import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def main():
    db = SessionLocal()
    
    try:
        symbol = "SOL_USDT"
        
        # Get watchlist item
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
        
        print("="*80)
        print(f"STATUS CHECK FOR {symbol}")
        print("="*80)
        
        if not watchlist_item:
            print(f"\n❌ {symbol} NOT FOUND in watchlist")
            print("\n⚠️  To enable automatic order creation:")
            print("   1. Add SOL_USDT to the watchlist via dashboard")
            print("   2. Set 'Trade' = YES")
            print("   3. Set 'Amount USD' > 0 (e.g., 100)")
            print("   4. Set 'Alert' = YES (optional, for Telegram alerts)")
            return 1
        
        print(f"\n✅ {symbol} FOUND in watchlist")
        print(f"\n📋 Configuration:")
        print(f"   - Trade Enabled: {'✅ YES' if watchlist_item.trade_enabled else '❌ NO'}")
        print(f"   - Alert Enabled: {'✅ YES' if watchlist_item.alert_enabled else '❌ NO'}")
        print(f"   - Amount USD: ${watchlist_item.trade_amount_usd:,.2f}" if watchlist_item.trade_amount_usd else "   - Amount USD: ❌ NOT CONFIGURED")
        print(f"   - Margin: {'✅ YES' if watchlist_item.trade_on_margin else '❌ NO'}")
        print(f"   - SL Mode: {watchlist_item.sl_tp_mode or 'conservative'}")
        print(f"   - Price: ${watchlist_item.price:,.4f}" if watchlist_item.price else "   - Price: Not set")
        
        # Check conditions for automatic order creation
        print(f"\n🔍 Conditions for Automatic Order Creation:")
        print(f"   - trade_enabled = true: {'✅' if watchlist_item.trade_enabled else '❌'}")
        print(f"   - trade_amount_usd > 0: {'✅' if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else '❌'}")
        
        can_create_order = (
            watchlist_item.trade_enabled and
            watchlist_item.trade_amount_usd and
            watchlist_item.trade_amount_usd > 0
        )
        
        if can_create_order:
            print(f"\n✅ ALL CONDITIONS MET - Orders will be created automatically when BUY signal is detected")
            print(f"\n💡 Note: The simulate-alert endpoint only sends Telegram alerts.")
            print(f"   Orders are created by the signal_monitor service when it detects a real BUY signal.")
            print(f"\n   To trigger an order immediately, you can:")
            print(f"   1. Wait for signal_monitor to detect a real BUY signal")
            print(f"   2. Or use the manual trade endpoint: POST /manual-trade/confirm")
        else:
            print(f"\n❌ CONDITIONS NOT MET - Orders will NOT be created automatically")
            print(f"\n⚠️  To enable automatic order creation:")
            if not watchlist_item.trade_enabled:
                print(f"   - Set 'Trade' = YES in the dashboard")
            if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
                print(f"   - Set 'Amount USD' > 0 in the dashboard (e.g., 100)")
        
        print("\n" + "="*80)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(main())

