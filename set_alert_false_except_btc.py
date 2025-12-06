#!/usr/bin/env python3
"""Script para establecer alert_enabled=False para todas las monedas excepto BTC_USDT"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def set_alert_false_except_btc():
    """Establece alert_enabled=False para todas las monedas excepto BTC_USDT"""
    db = SessionLocal()
    try:
        # Get all watchlist items
        all_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        if not all_items:
            logger.warning("No se encontraron monedas en el watchlist")
            return
        
        logger.info(f"📊 Encontradas {len(all_items)} monedas en el watchlist")
        
        updated_count = 0
        btc_updated = False
        
        for item in all_items:
            symbol = item.symbol.upper() if item.symbol else ""
            
            if symbol == "BTC_USDT":
                # Para BTC_USDT, asegurarse de que alert_enabled = True
                if not item.alert_enabled:
                    item.alert_enabled = True
                    db.commit()
                    logger.info(f"✅ BTC_USDT: alert_enabled establecido a True")
                    btc_updated = True
                else:
                    logger.info(f"✅ BTC_USDT: alert_enabled ya está en True (sin cambios)")
            else:
                # Para todas las demás monedas, establecer alert_enabled = False
                if item.alert_enabled:
                    item.alert_enabled = False
                    updated_count += 1
                    logger.info(f"🔴 {symbol}: alert_enabled establecido a False")
                else:
                    logger.debug(f"⚪ {symbol}: alert_enabled ya está en False (sin cambios)")
        
        # Commit all changes
        db.commit()
        
        logger.info("\n" + "="*80)
        logger.info("✅ PROCESO COMPLETADO")
        logger.info("="*80)
        logger.info(f"📊 Total de monedas procesadas: {len(all_items)}")
        logger.info(f"🔴 Monedas actualizadas a alert_enabled=False: {updated_count}")
        if btc_updated:
            logger.info(f"✅ BTC_USDT: alert_enabled establecido a True")
        else:
            logger.info(f"✅ BTC_USDT: alert_enabled ya estaba en True")
        logger.info("="*80)
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error al actualizar alert_enabled: {e}", exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    print("="*80)
    print("🔧 CONFIGURANDO ALERT_ENABLED")
    print("="*80)
    print("📋 Acción: Establecer alert_enabled=False para todas las monedas")
    print("📋 Excepción: BTC_USDT mantendrá alert_enabled=True")
    print("="*80)
    print()
    
    try:
        set_alert_false_except_btc()
        print("\n✅ Script ejecutado exitosamente")
    except Exception as e:
        print(f"\n❌ Error ejecutando el script: {e}")
        sys.exit(1)

