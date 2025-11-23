# Instrucciones para Actualizar Monedas en AWS

Este script actualiza todas las monedas en el servidor de AWS para que tengan:
- `alert_enabled = False` (Alert NO)
- `trade_enabled = False` (Trade NO)  
- `trade_on_margin = False` (Margin NO)

## Opción 1: Ejecutar directamente en AWS (Recomendado)

1. **Conectarse al servidor de AWS:**
   ```bash
   ssh ubuntu@54.254.150.31
   ```

2. **Navegar al directorio del proyecto:**
   ```bash
   cd ~/automated-trading-platform
   ```

3. **Copiar el script (si no está ya en el servidor):**
   ```bash
   # Desde tu máquina local, copia el script:
   scp update_all_coins_aws.py ubuntu@54.254.150.31:~/automated-trading-platform/
   ```

4. **Ejecutar el script dentro del contenedor Docker del backend:**
   ```bash
   docker compose exec -T backend python3 /app/update_all_coins_aws.py
   ```
   
   O si el script está en el directorio del proyecto:
   ```bash
   docker compose cp update_all_coins_aws.py backend:/app/update_all_coins_aws.py
   docker compose exec -T backend python3 /app/update_all_coins_aws.py
   ```

## Opción 2: Ejecutar desde línea de comandos del contenedor

1. **Entrar al contenedor:**
   ```bash
   docker compose exec backend bash
   ```

2. **Dentro del contenedor, ejecutar:**
   ```bash
   python3 << 'PYTHON_SCRIPT'
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
       logger.info(f"📊 Encontradas {len(all_items)} monedas")
       
       updated = 0
       for item in all_items:
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
               updated += 1
               logger.info(f"🔴 {item.symbol}: actualizado")
       
       db.commit()
       logger.info(f"✅ {updated} monedas actualizadas")
   except Exception as e:
       db.rollback()
       logger.error(f"❌ Error: {e}")
       raise
   finally:
       db.close()
   PYTHON_SCRIPT
   ```

## Opción 3: Usar el script bash (si tienes acceso SSH configurado)

Desde tu máquina local:
```bash
./update_coins_aws.sh
```

## Verificación

Después de ejecutar el script, verifica que todas las monedas tienen los valores correctos:

```bash
docker compose exec -T backend python3 << 'PYTHON_SCRIPT'
import sys
sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

db = SessionLocal()
try:
    total = db.query(WatchlistItem).count()
    alert_enabled = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).count()
    trade_enabled = db.query(WatchlistItem).filter(WatchlistItem.trade_enabled == True).count()
    margin = db.query(WatchlistItem).filter(WatchlistItem.trade_on_margin == True).count()
    
    print(f"Total monedas: {total}")
    print(f"Con alert_enabled=True: {alert_enabled}")
    print(f"Con trade_enabled=True: {trade_enabled}")
    print(f"Con trade_on_margin=True: {margin}")
    
    if alert_enabled == 0 and trade_enabled == 0 and margin == 0:
        print("\n✅ PERFECTO: Todas las monedas están desactivadas")
    else:
        print(f"\n⚠️ AÚN HAY MONEDAS ACTIVAS")
finally:
    db.close()
PYTHON_SCRIPT
```

