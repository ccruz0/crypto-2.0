#!/usr/bin/env python3
"""Script para verificar y actualizar el trade_amount_usd de BONK_USDT"""
import sys
import os

# Add backend to path
if os.path.exists(os.path.join(os.path.dirname(__file__), 'backend')):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_bonk_trade_amount():
    """Verifica el trade_amount_usd de BONK_USDT"""
    db = SessionLocal()
    try:
        # Buscar BONK_USDT en la watchlist
        bonk_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == "BONK_USDT"
        ).first()
        
        if not bonk_item:
            logger.error("❌ BONK_USDT no encontrado en la watchlist")
            return
        
        logger.info(f"📊 BONK_USDT encontrado:")
        logger.info(f"   - Symbol: {bonk_item.symbol}")
        logger.info(f"   - trade_amount_usd: ${bonk_item.trade_amount_usd:,.2f}" if bonk_item.trade_amount_usd else f"   - trade_amount_usd: None")
        logger.info(f"   - trade_enabled: {bonk_item.trade_enabled}")
        logger.info(f"   - alert_enabled: {bonk_item.alert_enabled}")
        logger.info(f"   - sell_alert_enabled: {bonk_item.sell_alert_enabled}")
        logger.info(f"   - trade_on_margin: {bonk_item.trade_on_margin}")
        
        if bonk_item.trade_amount_usd == 10000:
            logger.warning("⚠️  El trade_amount_usd está configurado en $10,000")
            logger.info("💡 Para cambiarlo, puedes:")
            logger.info("   1. Usar el Dashboard y editar el campo 'Amount USD' para BONK_USDT")
            logger.info("   2. O ejecutar este script con un argumento: python check_bonk_trade_amount.py <nuevo_valor>")
            
            # Si se proporciona un nuevo valor como argumento
            if len(sys.argv) > 1:
                try:
                    new_value = float(sys.argv[1])
                    if new_value > 0:
                        bonk_item.trade_amount_usd = new_value
                        db.commit()
                        logger.info(f"✅ Actualizado trade_amount_usd a ${new_value:,.2f}")
                    else:
                        logger.error("❌ El valor debe ser mayor que 0")
                except ValueError:
                    logger.error(f"❌ Valor inválido: {sys.argv[1]}")
        else:
            logger.info(f"✅ El trade_amount_usd actual es ${bonk_item.trade_amount_usd:,.2f}")
            
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    check_bonk_trade_amount()



















