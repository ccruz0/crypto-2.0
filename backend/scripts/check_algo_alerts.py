#!/usr/bin/env python3
"""Quick script to check ALGO alert status"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.watchlist import WatchlistItem

def main():
    db = create_db_session()
    try:
        symbol = "ALGO_USDT"
        
        # Try to get watchlist item, handling missing columns gracefully
        try:
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
        except Exception as e:
            # If query fails due to missing columns, try raw SQL
            result = db.execute(
                "SELECT alert_enabled, buy_alert_enabled, sell_alert_enabled, trade_enabled FROM watchlist_items WHERE symbol = ?",
                (symbol,)
            ).fetchone()
            
            if result:
                alert_enabled, buy_alert_enabled, sell_alert_enabled, trade_enabled = result
                print(f"📊 ALGO_USDT Alert Status:")
                print(f"  • alert_enabled: {bool(alert_enabled) if alert_enabled is not None else False}")
                print(f"  • buy_alert_enabled: {buy_alert_enabled}")
                print(f"  • sell_alert_enabled: {sell_alert_enabled}")
                print(f"  • trade_enabled: {bool(trade_enabled) if trade_enabled is not None else False}")
                
                # Determine if alerts are effectively enabled
                alert_enabled_bool = bool(alert_enabled) if alert_enabled is not None else False
                buy_enabled = buy_alert_enabled if buy_alert_enabled is not None else (alert_enabled_bool)
                sell_enabled = sell_alert_enabled if sell_alert_enabled is not None else (alert_enabled_bool)
                
                print()
                print("✅ RESULTADO:")
                if alert_enabled_bool:
                    print(f"  • Master alert (alert_enabled): ✅ ENABLED")
                    if buy_enabled:
                        print(f"  • BUY alerts: ✅ ENABLED")
                    else:
                        print(f"  • BUY alerts: ❌ DISABLED")
                    if sell_enabled:
                        print(f"  • SELL alerts: ✅ ENABLED")
                    else:
                        print(f"  • SELL alerts: ❌ DISABLED")
                else:
                    print(f"  • Master alert (alert_enabled): ❌ DISABLED")
                    print(f"  • BUY alerts: ❌ DISABLED (master switch off)")
                    print(f"  • SELL alerts: ❌ DISABLED (master switch off)")
            else:
                print(f"❌ {symbol} not found in watchlist")
            return
        
        if not watchlist_item:
            print(f"❌ {symbol} not found in watchlist")
            return
        
        # Get alert flags
        alert_enabled = getattr(watchlist_item, 'alert_enabled', False)
        buy_alert_enabled = getattr(watchlist_item, 'buy_alert_enabled', None)
        sell_alert_enabled = getattr(watchlist_item, 'sell_alert_enabled', None)
        trade_enabled = getattr(watchlist_item, 'trade_enabled', False)
        
        print(f"📊 ALGO_USDT Alert Status:")
        print(f"  • alert_enabled: {alert_enabled}")
        print(f"  • buy_alert_enabled: {buy_alert_enabled}")
        print(f"  • sell_alert_enabled: {sell_alert_enabled}")
        print(f"  • trade_enabled: {trade_enabled}")
        print()
        
        # Determine effective status
        # If alert_enabled=True and buy_alert_enabled is None, it defaults to True
        buy_effectively_enabled = buy_alert_enabled if buy_alert_enabled is not None else (alert_enabled if alert_enabled else False)
        sell_effectively_enabled = sell_alert_enabled if sell_alert_enabled is not None else (alert_enabled if alert_enabled else False)
        
        print("✅ RESULTADO:")
        if alert_enabled:
            print(f"  • Master alert (alert_enabled): ✅ ENABLED")
            if buy_effectively_enabled:
                print(f"  • BUY alerts: ✅ ENABLED")
            else:
                print(f"  • BUY alerts: ❌ DISABLED")
            if sell_effectively_enabled:
                print(f"  • SELL alerts: ✅ ENABLED")
            else:
                print(f"  • SELL alerts: ❌ DISABLED")
        else:
            print(f"  • Master alert (alert_enabled): ❌ DISABLED")
            print(f"  • BUY alerts: ❌ DISABLED (master switch off)")
            print(f"  • SELL alerts: ❌ DISABLED (master switch off)")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()





