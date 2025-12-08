#!/usr/bin/env python3
"""
Script para listar todos los valores de trade_amount_usd para todas las monedas
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def list_trade_amounts():
    """Lista todos los valores de trade_amount_usd"""
    db = SessionLocal()
    try:
        # Get all watchlist items
        items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).order_by(WatchlistItem.symbol).all()
        
        print("=" * 80)
        print(f"{'Símbolo':<15} {'Exchange':<15} {'Trade Amount (USD)':<20} {'Trade Enabled':<15} {'Alert Enabled':<15}")
        print("=" * 80)
        
        total_count = 0
        with_amount = 0
        total_amount = 0.0
        
        for item in items:
            trade_amount = item.trade_amount_usd if item.trade_amount_usd is not None else "NULL"
            trade_enabled = "✅ YES" if item.trade_enabled else "❌ NO"
            alert_enabled = "✅ YES" if item.alert_enabled else "❌ NO"
            
            print(f"{item.symbol:<15} {item.exchange:<15} {str(trade_amount):<20} {trade_enabled:<15} {alert_enabled:<15}")
            
            total_count += 1
            if item.trade_amount_usd is not None:
                with_amount += 1
                total_amount += item.trade_amount_usd
        
        print("=" * 80)
        print(f"\n📊 Resumen:")
        print(f"   Total de monedas: {total_count}")
        print(f"   Monedas con trade_amount_usd configurado: {with_amount}")
        print(f"   Monedas sin trade_amount_usd: {total_count - with_amount}")
        if with_amount > 0:
            print(f"   Total en USD (suma de todos los trade_amount_usd): ${total_amount:,.2f}")
            print(f"   Promedio por moneda: ${total_amount/with_amount:,.2f}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    list_trade_amounts()

