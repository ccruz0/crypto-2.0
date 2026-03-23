#!/usr/bin/env python3
"""
Quick script to check margin trading setting for a symbol.
Usage: python scripts/check_margin_setting.py AAVE_USDT
"""
import sys
import os

# Add backend to path
backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_root)

from app.database import create_db_session
from app.models.watchlist import WatchlistItem

def check_margin_setting(symbol: str):
    """Check if margin trading is enabled for a symbol."""
    db = create_db_session()
    try:
        # Query watchlist item
        item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol.upper(),
            WatchlistItem.is_deleted == False
        ).first()
        
        if not item:
            print(f"❌ Symbol {symbol} not found in watchlist")
            return
        
        print(f"\n📊 Symbol: {item.symbol}")
        print(f"🏦 Exchange: {item.exchange}")
        print(f"✅ Trade Enabled: {item.trade_enabled}")
        print(f"💰 Trade Amount USD: {item.trade_amount_usd}")
        print(f"⚖️  Trade on Margin: {item.trade_on_margin}")
        print(f"🔔 Alert Enabled: {item.alert_enabled}")
        print(f"🟢 Buy Alert Enabled: {getattr(item, 'buy_alert_enabled', False)}")
        print(f"🔴 Sell Alert Enabled: {getattr(item, 'sell_alert_enabled', False)}")
        
        if item.trade_on_margin:
            print(f"\n✅ MARGIN TRADING IS ENABLED for {symbol}")
        else:
            print(f"\n❌ MARGIN TRADING IS DISABLED for {symbol}")
            
    except Exception as e:
        print(f"❌ Error checking margin setting: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAVE_USDT"
    check_margin_setting(symbol)







