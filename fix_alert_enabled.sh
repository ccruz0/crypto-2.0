#!/bin/bash
# Script para establecer alert_enabled=False para todas las monedas excepto BTC_USDT
# Se ejecuta dentro del contenedor Docker del backend

echo "================================================================================"
echo "🔧 CONFIGURANDO ALERT_ENABLED"
echo "================================================================================"
echo "📋 Acción: Establecer alert_enabled=False para todas las monedas"
echo "📋 Excepción: BTC_USDT mantendrá alert_enabled=True"
echo "================================================================================"
echo ""

# Ejecutar script Python dentro del contenedor
docker compose exec -T backend python3 << 'PYTHON_SCRIPT'
import sys
import os
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_alert_enabled():
    """Establece alert_enabled=False para todas las monedas excepto BTC_USDT"""
    db = SessionLocal()
    try:
        # Get all watchlist items
        all_items = db.query(WatchlistItem).all()
        
        if not all_items:
            logger.warning("No se encontraron monedas en el watchlist")
            return
        
        logger.info(f"📊 Encontradas {len(all_items)} monedas en el watchlist")
        
        updated_count = 0
        btc_updated = False
        already_false_count = 0
        
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
                    already_false_count += 1
                    logger.debug(f"⚪ {symbol}: alert_enabled ya está en False (sin cambios)")
        
        # Commit all changes
        db.commit()
        
        logger.info("\n" + "="*80)
        logger.info("✅ PROCESO COMPLETADO")
        logger.info("="*80)
        logger.info(f"📊 Total de monedas procesadas: {len(all_items)}")
        logger.info(f"🔴 Monedas actualizadas a alert_enabled=False: {updated_count}")
        logger.info(f"⚪ Monedas que ya tenían alert_enabled=False: {already_false_count}")
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
    try:
        fix_alert_enabled()
        print("\n✅ Script ejecutado exitosamente")
    except Exception as e:
        print(f"\n❌ Error ejecutando el script: {e}")
        sys.exit(1)
PYTHON_SCRIPT

echo ""
echo "================================================================================"
echo "✅ Script completado"
echo "================================================================================"

