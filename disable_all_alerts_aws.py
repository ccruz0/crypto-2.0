#!/usr/bin/env python3
"""
Script para desactivar todas las alertas en AWS
Pone alert_enabled=False para todas las monedas en watchlist_items
"""
import sys
import os

# Add the app directory to the path
sys.path.insert(0, '/app')

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def disable_all_alerts():
    """Desactiva todas las alertas en la base de datos"""
    db: Session = SessionLocal()
    try:
        # Obtener todas las monedas
        all_coins = db.query(WatchlistItem).all()
        
        if not all_coins:
            logger.info("⚠️  No se encontraron monedas en watchlist_items")
            return
        
        logger.info(f"📊 Encontradas {len(all_coins)} monedas en watchlist_items")
        
        # Contar cuántas tienen alert_enabled=True
        enabled_count = sum(1 for coin in all_coins if coin.alert_enabled)
        logger.info(f"📈 Monedas con alert_enabled=True: {enabled_count}")
        
        # Actualizar todas las monedas
        updated_count = 0
        for coin in all_coins:
            if coin.alert_enabled:
                coin.alert_enabled = False
                coin.trade_enabled = False
                coin.trade_on_margin = False
                updated_count += 1
                logger.info(f"  ✅ Actualizado: {coin.symbol} - alert_enabled=False, trade_enabled=False, trade_on_margin=False")
        
        if updated_count > 0:
            db.commit()
            logger.info(f"✅ Se actualizaron {updated_count} monedas")
        else:
            logger.info("ℹ️  Todas las monedas ya tienen alert_enabled=False")
        
        # Verificar resultado
        db.refresh(all_coins[0] if all_coins else None)
        remaining_enabled = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).count()
        logger.info(f"📊 Monedas con alert_enabled=True después de actualización: {remaining_enabled}")
        
        if remaining_enabled == 0:
            logger.info("✅ ÉXITO: Todas las alertas están desactivadas")
        else:
            logger.warning(f"⚠️  Aún quedan {remaining_enabled} monedas con alert_enabled=True")
            
    except Exception as e:
        logger.error(f"❌ Error al desactivar alertas: {e}", exc_info=True)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("🚫 DESACTIVANDO TODAS LAS ALERTAS EN AWS")
    logger.info("=" * 80)
    disable_all_alerts()
    logger.info("=" * 80)
    logger.info("✅ PROCESO COMPLETADO")
    logger.info("=" * 80)

