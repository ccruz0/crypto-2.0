# Desactivar Todas las Alertas en AWS

Este documento explica cómo desactivar todas las alertas en el servidor AWS.

## Opción 1: Ejecutar directamente en AWS (Recomendado)

Si tienes acceso SSH al servidor AWS:

```bash
# Conectarse al servidor AWS
ssh ubuntu@54.254.150.31

# Una vez conectado, ejecutar:
cd ~/crypto-2.0
docker compose exec -T backend-aws python3 << 'EOF'
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
EOF
```

## Opción 2: Usar AWS Systems Manager (SSM)

Si tienes AWS CLI configurado y permisos de SSM:

```bash
# Ejecutar el script usando SSM
./disable_alerts_aws_ssm.sh
```

O manualmente:

```bash
aws ssm send-command \
    --instance-ids i-087953603011543c5 \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "cd /home/ubuntu/crypto-2.0",
        "docker compose exec -T backend-aws python3 -c \"import sys; sys.path.insert(0, \\\"/app\\\"); from sqlalchemy.orm import Session; from app.database import SessionLocal; from app.models.watchlist import WatchlistItem; db = SessionLocal(); coins = db.query(WatchlistItem).all(); [setattr(c, \\\"alert_enabled\\\", False) or setattr(c, \\\"trade_enabled\\\", False) or setattr(c, \\\"trade_on_margin\\\", False) for c in coins if c.alert_enabled]; db.commit(); print(f\\\"✅ Actualizadas {sum(1 for c in coins if c.alert_enabled)} monedas\\\"); db.close()\""
    ]' \
    --region ap-southeast-1
```

## Opción 3: Copiar script y ejecutar

1. Copiar el script `disable_all_alerts_aws.py` al servidor:

```bash
scp disable_all_alerts_aws.py ubuntu@54.254.150.31:~/crypto-2.0/
```

2. Ejecutar en el servidor:

```bash
ssh ubuntu@54.254.150.31
cd ~/crypto-2.0
docker compose exec -T backend-aws python3 disable_all_alerts_aws.py
```

## Verificación

Después de ejecutar el script, verifica que todas las alertas estén desactivadas:

```bash
docker compose exec -T backend-aws python3 << 'EOF'
import sys
sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

db = SessionLocal()
enabled_count = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).count()
total_count = db.query(WatchlistItem).count()
print(f"📊 Total monedas: {total_count}")
print(f"🔴 Monedas con alert_enabled=True: {enabled_count}")
print(f"✅ Monedas con alert_enabled=False: {total_count - enabled_count}")
db.close()
EOF
```

## Notas

- El script desactiva `alert_enabled`, `trade_enabled` y `trade_on_margin` para todas las monedas
- Los cambios se guardan inmediatamente en la base de datos
- El SignalMonitorService dejará de enviar alertas automáticamente
- Puedes reactivar alertas individuales desde el dashboard o la API

