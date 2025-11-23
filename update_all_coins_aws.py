#!/usr/bin/env python3
"""Script para actualizar todas las monedas en AWS: alert_enabled=False, trade_enabled=False, trade_on_margin=False"""
import sys
import os

# Add /app to path (Docker container path)
if '/app' not in sys.path:
    sys.path.insert(0, '/app')

# Also try backend path for local execution
if os.path.exists(os.path.join(os.path.dirname(__file__), 'backend')):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_all_coins():
    """Establece alert_enabled=False, trade_enabled=False, trade_on_margin=False para todas las monedas"""
    db = SessionLocal()
    try:
        # Get all watchlist items
        all_items = db.query(WatchlistItem).all()
        
        if not all_items:
            logger.warning("No se encontraron monedas en el watchlist")
            return
        
        logger.info(f"📊 Encontradas {len(all_items)} monedas en el watchlist")
        
        updated_count = 0
        already_set_count = 0
        
        for item in all_items:
            symbol = item.symbol.upper() if item.symbol else ""
            needs_update = False
            
            # Check what needs to be updated
            if item.alert_enabled != False:
                item.alert_enabled = False
                needs_update = True
            if item.trade_enabled != False:
                item.trade_enabled = False
                needs_update = True
            if hasattr(item, 'trade_on_margin') and item.trade_on_margin != False:
                item.trade_on_margin = False
                needs_update = True
            
            if needs_update:
                updated_count += 1
                logger.info(
                    f"🔴 {symbol}: "
                    f"alert_enabled={item.alert_enabled}, "
                    f"trade_enabled={item.trade_enabled}, "
                    f"trade_on_margin={getattr(item, 'trade_on_margin', 'N/A')}"
                )
            else:
                already_set_count += 1
                logger.debug(
                    f"⚪ {symbol}: Ya tiene todos los valores en False (sin cambios)"
                )
        
        # Commit all changes
        db.commit()
        
        logger.info("\n" + "="*80)
        logger.info("✅ PROCESO COMPLETADO")
        logger.info("="*80)
        logger.info(f"📊 Total de monedas procesadas: {len(all_items)}")
        logger.info(f"🔴 Monedas actualizadas: {updated_count}")
        logger.info(f"⚪ Monedas que ya tenían los valores correctos: {already_set_count}")
        logger.info("="*80)
        
        # Show summary by status
        logger.info("\n📋 RESUMEN POR ESTADO:")
        alert_enabled_count = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).count()
        trade_enabled_count = db.query(WatchlistItem).filter(WatchlistItem.trade_enabled == True).count()
        margin_count = db.query(WatchlistItem).filter(WatchlistItem.trade_on_margin == True).count() if hasattr(WatchlistItem, 'trade_on_margin') else 0
        
        logger.info(f"  • Monedas con alert_enabled=True: {alert_enabled_count}")
        logger.info(f"  • Monedas con trade_enabled=True: {trade_enabled_count}")
        logger.info(f"  • Monedas con trade_on_margin=True: {margin_count}")
        
        if alert_enabled_count == 0 and trade_enabled_count == 0 and margin_count == 0:
            logger.info("\n✅ PERFECTO: Todas las monedas tienen alert_enabled=False, trade_enabled=False, trade_on_margin=False")
        else:
            logger.warning(f"\n⚠️ AÚN HAY MONEDAS ACTIVAS: {alert_enabled_count} alert, {trade_enabled_count} trade, {margin_count} margin")
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error al actualizar monedas: {e}", exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    try:
        update_all_coins()
        print("\n✅ Script ejecutado exitosamente")
    except Exception as e:
        print(f"\n❌ Error ejecutando el script: {e}")
        sys.exit(1)

