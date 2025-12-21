#!/usr/bin/env python3
"""Script to check sell_alert_enabled status for all watchlist items"""
import sys
import os

# Add backend to path if running from project root
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
if os.path.exists(backend_path):
    sys.path.insert(0, backend_path)
else:
    # If running from inside backend container, backend is already in path
    pass

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def check_sell_alert_enabled():
    """Check sell_alert_enabled status for all watchlist items"""
    db = SessionLocal()
    try:
        # Get all watchlist items with alert_enabled=True
        items = db.query(WatchlistItem).filter(
            WatchlistItem.alert_enabled == True
        ).order_by(WatchlistItem.symbol).all()
        
        if not items:
            print("❌ No watchlist items found with alert_enabled=True")
            return
        
        print(f"\n📊 Estado de sell_alert_enabled para {len(items)} símbolos:\n")
        print(f"{'Symbol':<20} | {'alert_enabled':<15} | {'buy_alert_enabled':<18} | {'sell_alert_enabled':<19}")
        print("-" * 80)
        
        sell_disabled_count = 0
        sell_enabled_count = 0
        
        for item in items:
            alert = item.alert_enabled
            buy = getattr(item, 'buy_alert_enabled', False)
            sell = getattr(item, 'sell_alert_enabled', False)
            
            symbol = item.symbol or "N/A"
            alert_str = "✅ True" if alert else "❌ False"
            buy_str = "✅ True" if buy else "❌ False"
            sell_str = "✅ True" if sell else "❌ False"
            
            print(f"{symbol:<20} | {alert_str:<15} | {buy_str:<18} | {sell_str:<19}")
            
            if sell:
                sell_enabled_count += 1
            else:
                sell_disabled_count += 1
        
        print("-" * 80)
        print(f"\n📈 Resumen:")
        print(f"   ✅ sell_alert_enabled=True: {sell_enabled_count} símbolos")
        print(f"   ❌ sell_alert_enabled=False: {sell_disabled_count} símbolos")
        print(f"   📊 Total: {len(items)} símbolos")
        
        if sell_disabled_count > 0:
            print(f"\n⚠️  PROBLEMA: {sell_disabled_count} símbolos tienen sell_alert_enabled=False")
            print("   Esto explica por qué no recibes señales SELL.")
            print("\n💡 Solución:")
            print("   Para habilitar alertas SELL, actualiza la watchlist desde el dashboard")
            print("   o ejecuta:")
            print("   UPDATE watchlist_items SET sell_alert_enabled = true WHERE alert_enabled = true;")
        
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_sell_alert_enabled()





