#!/usr/bin/env python3
"""Script para verificar el estado de alert_enabled de todas las monedas"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_alert_status():
    """Verifica el estado de alert_enabled de todas las monedas"""
    db = SessionLocal()
    try:
        # Get all watchlist items
        all_items = db.query(WatchlistItem).all()
        
        if not all_items:
            logger.warning("No se encontraron monedas en el watchlist")
            return
        
        print("="*80)
        print("📊 ESTADO DE ALERT_ENABLED PARA TODAS LAS MONEDAS")
        print("="*80)
        print()
        
        # Separate by alert_enabled status
        alert_enabled_coins = []
        alert_disabled_coins = []
        
        for item in all_items:
            symbol = item.symbol.upper() if item.symbol else "N/A"
            alert_status = item.alert_enabled if hasattr(item, 'alert_enabled') else None
            trade_status = item.trade_enabled if hasattr(item, 'trade_enabled') else None
            
            coin_info = {
                'symbol': symbol,
                'alert_enabled': alert_status,
                'trade_enabled': trade_status,
                'id': item.id
            }
            
            if alert_status:
                alert_enabled_coins.append(coin_info)
            else:
                alert_disabled_coins.append(coin_info)
        
        print(f"🟢 MONEDAS CON alert_enabled=True ({len(alert_enabled_coins)}):")
        print("-"*80)
        if alert_enabled_coins:
            for coin in sorted(alert_enabled_coins, key=lambda x: x['symbol']):
                trade_text = "✅ Trade=YES" if coin['trade_enabled'] else "❌ Trade=NO"
                print(f"  • {coin['symbol']:15} | ID: {coin['id']:3} | {trade_text}")
        else:
            print("  (ninguna)")
        print()
        
        print(f"🔴 MONEDAS CON alert_enabled=False ({len(alert_disabled_coins)}):")
        print("-"*80)
        if alert_disabled_coins:
            for coin in sorted(alert_disabled_coins, key=lambda x: x['symbol']):
                trade_text = "✅ Trade=YES" if coin['trade_enabled'] else "❌ Trade=NO"
                print(f"  • {coin['symbol']:15} | ID: {coin['id']:3} | {trade_text}")
        else:
            print("  (ninguna)")
        print()
        
        # Check specifically for ADA_USD
        ada_usd_items = [item for item in all_items if item.symbol and item.symbol.upper() == "ADA_USD"]
        if ada_usd_items:
            print("="*80)
            print("🔍 VERIFICACIÓN ESPECÍFICA: ADA_USD")
            print("="*80)
            for item in ada_usd_items:
                print(f"  • Symbol: {item.symbol}")
                print(f"  • ID: {item.id}")
                print(f"  • alert_enabled: {item.alert_enabled if hasattr(item, 'alert_enabled') else 'N/A'}")
                print(f"  • trade_enabled: {item.trade_enabled if hasattr(item, 'trade_enabled') else 'N/A'}")
                print(f"  • is_deleted: {getattr(item, 'is_deleted', 'N/A')}")
                print()
        else:
            print("⚠️ ADA_USD no encontrado en el watchlist")
            print()
        
        # Check for ADA_USDT as well
        ada_usdt_items = [item for item in all_items if item.symbol and item.symbol.upper() == "ADA_USDT"]
        if ada_usdt_items:
            print("="*80)
            print("🔍 VERIFICACIÓN ESPECÍFICA: ADA_USDT")
            print("="*80)
            for item in ada_usdt_items:
                print(f"  • Symbol: {item.symbol}")
                print(f"  • ID: {item.id}")
                print(f"  • alert_enabled: {item.alert_enabled if hasattr(item, 'alert_enabled') else 'N/A'}")
                print(f"  • trade_enabled: {item.trade_enabled if hasattr(item, 'trade_enabled') else 'N/A'}")
                print(f"  • is_deleted: {getattr(item, 'is_deleted', 'N/A')}")
                print()
        
        print("="*80)
        print("📋 RESUMEN")
        print("="*80)
        print(f"  • Total monedas: {len(all_items)}")
        print(f"  • Con alert_enabled=True: {len(alert_enabled_coins)}")
        print(f"  • Con alert_enabled=False: {len(alert_disabled_coins)}")
        print()
        print("💡 Si recibes alertas de monedas con alert_enabled=False:")
        print("   1. Verifica que el valor en la base de datos sea realmente False")
        print("   2. Revisa los logs del backend para ver si hay errores en el refresh")
        print("   3. Verifica que no haya múltiples entradas para el mismo símbolo")
        print("="*80)
        
    except Exception as e:
        logger.error(f"❌ Error verificando alert status: {e}", exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    check_alert_status()

