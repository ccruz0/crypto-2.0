#!/bin/bash
# Script simplificado para desactivar alertas en AWS
# Ejecutar directamente en el servidor AWS

set -e

echo "🚫 Desactivando todas las alertas en AWS..."
echo "📋 Este script debe ejecutarse en el servidor AWS"
echo ""

# Primero, copiar el script Python al servidor si no existe
if [ ! -f "/tmp/disable_alerts_aws.py" ]; then
    echo "⚠️  El script Python no está en /tmp/"
    echo "📝 Creando script Python..."
    cat > /tmp/disable_alerts_aws.py << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def disable_all_alerts():
    db: Session = SessionLocal()
    try:
        all_coins = db.query(WatchlistItem).all()
        if not all_coins:
            logger.info("⚠️  No se encontraron monedas")
            return
        
        logger.info(f"📊 Encontradas {len(all_coins)} monedas")
        enabled_count = sum(1 for coin in all_coins if coin.alert_enabled)
        logger.info(f"📈 Monedas con alert_enabled=True: {enabled_count}")
        
        updated_count = 0
        for coin in all_coins:
            if coin.alert_enabled:
                coin.alert_enabled = False
                coin.trade_enabled = False
                coin.trade_on_margin = False
                updated_count += 1
                logger.info(f"  ✅ {coin.symbol} - alert_enabled=False")
        
        if updated_count > 0:
            db.commit()
            logger.info(f"✅ Actualizadas {updated_count} monedas")
        
        remaining = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).count()
        logger.info(f"📊 Monedas con alert_enabled=True después: {remaining}")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    disable_all_alerts()
PYTHON_SCRIPT
fi

echo "🔧 Ejecutando script dentro del contenedor Docker..."
docker compose exec -T backend-aws python3 << 'PYTHON_SCRIPT'
import sys
sys.path.insert(0, '/app')

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def disable_all_alerts():
    db: Session = SessionLocal()
    try:
        all_coins = db.query(WatchlistItem).all()
        if not all_coins:
            logger.info("⚠️  No se encontraron monedas")
            return
        
        logger.info(f"📊 Encontradas {len(all_coins)} monedas")
        enabled_count = sum(1 for coin in all_coins if coin.alert_enabled)
        logger.info(f"📈 Monedas con alert_enabled=True: {enabled_count}")
        
        updated_count = 0
        for coin in all_coins:
            if coin.alert_enabled:
                coin.alert_enabled = False
                coin.trade_enabled = False
                coin.trade_on_margin = False
                updated_count += 1
                logger.info(f"  ✅ {coin.symbol} - alert_enabled=False")
        
        if updated_count > 0:
            db.commit()
            logger.info(f"✅ Actualizadas {updated_count} monedas")
        
        remaining = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).count()
        logger.info(f"📊 Monedas con alert_enabled=True después: {remaining}")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

disable_all_alerts()
PYTHON_SCRIPT

echo ""
echo "✅ Proceso completado"

