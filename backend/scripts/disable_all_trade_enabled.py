#!/usr/bin/env python3
"""
Script para desactivar trade_enabled en todas las monedas de la watchlist.
Esto previene que se ejecuten órdenes automáticas.

Uso:
    python backend/scripts/disable_all_trade_enabled.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.watchlist import WatchlistItem
from sqlalchemy import update

def disable_all_trade_enabled():
    """Desactiva trade_enabled para todas las monedas en la watchlist"""
    db = create_db_session()
    try:
        # Get all watchlist items
        all_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        print(f"📊 Encontradas {len(all_items)} monedas en la watchlist")
        
        # Count how many have trade_enabled = True
        enabled_count = sum(1 for item in all_items if item.trade_enabled)
        print(f"🔍 Monedas con trade_enabled=True: {enabled_count}")
        
        if enabled_count == 0:
            print("✅ Todas las monedas ya tienen trade_enabled=False")
            return
        
        # Update all items to set trade_enabled = False
        updated = db.execute(
            update(WatchlistItem)
            .where(WatchlistItem.is_deleted == False)
            .values(trade_enabled=False)
        )
        
        db.commit()
        
        print(f"✅ Desactivado trade_enabled para {updated.rowcount} monedas")
        
        # Verify the update
        remaining_enabled = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False,
            WatchlistItem.trade_enabled == True
        ).count()
        
        if remaining_enabled == 0:
            print("✅ Verificación exitosa: Todas las monedas tienen trade_enabled=False")
        else:
            print(f"⚠️ ADVERTENCIA: {remaining_enabled} monedas aún tienen trade_enabled=True")
            
        # List all items with their current status
        print("\n📋 Estado actual de todas las monedas:")
        all_items_after = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        for item in sorted(all_items_after, key=lambda x: x.symbol):
            status = "✅ DESACTIVADO" if not item.trade_enabled else "❌ ACTIVADO"
            alert_status = "🔔" if item.alert_enabled else "🔕"
            print(f"   {item.symbol:15} | trade_enabled: {status:15} | alert_enabled: {alert_status}")
            
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    print("🚫 Desactivando trade_enabled para todas las monedas...")
    print("=" * 60)
    disable_all_trade_enabled()
    print("=" * 60)
    print("✅ Proceso completado")
