#!/bin/bash
# Script simple para ejecutar en AWS directamente

echo "========================================="
echo "Actualizando todas las monedas en AWS"
echo "========================================="
echo ""

docker compose exec -T backend python3 << 'PYTHON_SCRIPT'
import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = SessionLocal()
try:
    all_items = db.query(WatchlistItem).all()
    logger.info(f"📊 Encontradas {len(all_items)} monedas en el watchlist")
    
    updated_count = 0
    already_set_count = 0
    
    for item in all_items:
        symbol = item.symbol.upper() if item.symbol else ""
        needs_update = False
        
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
            logger.info(f"🔴 {symbol}: alert_enabled=False, trade_enabled=False, trade_on_margin=False")
        else:
            already_set_count += 1
    
    db.commit()
    
    logger.info("\n" + "="*80)
    logger.info("✅ PROCESO COMPLETADO")
    logger.info("="*80)
    logger.info(f"📊 Total de monedas procesadas: {len(all_items)}")
    logger.info(f"🔴 Monedas actualizadas: {updated_count}")
    logger.info(f"⚪ Monedas que ya tenían los valores correctos: {already_set_count}")
    
    # Verify
    alert_enabled_count = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).count()
    trade_enabled_count = db.query(WatchlistItem).filter(WatchlistItem.trade_enabled == True).count()
    margin_count = db.query(WatchlistItem).filter(WatchlistItem.trade_on_margin == True).count() if hasattr(WatchlistItem, 'trade_on_margin') else 0
    
    logger.info(f"\n📋 VERIFICACIÓN:")
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
PYTHON_SCRIPT

echo ""
echo "✅ Script completado"
