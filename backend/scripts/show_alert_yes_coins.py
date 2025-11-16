#!/usr/bin/env python3
"""Script to show coins with alert_enabled=YES created yesterday (index 1-100)"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def main():
    db = SessionLocal()
    try:
        # Get yesterday's date range (UTC)
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today - timedelta(days=1)
        yesterday_end = today
        
        print(f"📊 Monedas con ALERTA YES (todas, mostrando las más recientes primero)\n")
        print(f"Fecha de referencia: {yesterday_start.strftime('%Y-%m-%d')} UTC (ayer)\n")
        print(f"Rango: 1-100\n")
        print("-" * 80)
        
        # Query ALL watchlist items with alert_enabled=True (not just yesterday)
        all_items = db.query(WatchlistItem).filter(
            WatchlistItem.alert_enabled == True,
            WatchlistItem.is_deleted == False
        ).order_by(WatchlistItem.created_at.desc()).limit(200).all()
        
        if not all_items:
            print("❌ No se encontraron monedas con alerta YES.")
            return
        
        # Separate items created yesterday vs other dates
        yesterday_items = []
        other_items = []
        
        for item in all_items:
            if item.created_at:
                # Ensure timezone-aware comparison
                created_at = item.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                elif created_at.tzinfo != timezone.utc:
                    created_at = created_at.astimezone(timezone.utc)
                
                if created_at >= yesterday_start and created_at < yesterday_end:
                    yesterday_items.append(item)
                else:
                    other_items.append(item)
            else:
                other_items.append(item)
        
        # Show yesterday's items first, then others
        items = yesterday_items + other_items[:100-len(yesterday_items)]
        
        print(f"✅ Total encontradas: {len(all_items)} monedas con alerta YES")
        print(f"📅 Creadas ayer ({yesterday_start.strftime('%Y-%m-%d')}): {len(yesterday_items)}")
        print(f"📅 Creadas en otras fechas: {len(other_items)}\n")
        print("-" * 80)
        
        print(f"✅ Encontradas {len(items)} monedas:\n")
        
        # Display with index
        for index, item in enumerate(items, start=1):
            created_at_str = item.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') if item.created_at else 'N/A'
            trade_status = "✅ YES" if item.trade_enabled else "❌ NO"
            
            print(f"{index:3d}. {item.symbol:15s} | ID: {item.id:5d} | Trade: {trade_status:8s} | Creado: {created_at_str}")
        
        print("\n" + "-" * 80)
        print(f"Total: {len(items)} monedas")
        
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()


