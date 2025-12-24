# Deploy Watchlist Consistency Fix

## Resumen

Este deploy incluye correcciones para resolver discrepancias en el reporte de consistencia de watchlist:

1. **Valores por defecto** para campos críticos (sl_tp_mode, order_status, exchange)
2. **Logging mejorado** para identificar cuando MarketData está ausente o incompleto
3. **Scripts de verificación** para monitorear el estado de MarketData

## Cambios Implementados

### Archivo: `backend/app/api/routes_dashboard.py`

- Agregados valores por defecto para `sl_tp_mode`, `order_status`, y `exchange`
- Agregado logging cuando MarketData está ausente o incompleto
- Tracking de campos faltantes para debugging

### Nuevos Archivos

- `scripts/verify_market_data_status.py`: Script de verificación de MarketData
- `scripts/verify_market_data_status.sh`: Script bash alternativo
- `VERIFY_MARKET_DATA_INSTRUCTIONS.md`: Documentación de verificación
- `WATCHLIST_MISMATCH_ANALYSIS.md`: Análisis del problema
- `WATCHLIST_MISMATCH_FIXES_SUMMARY.md`: Resumen de correcciones

## Deploy en AWS

### Opción 1: Script Automático (Recomendado)

```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
git pull origin main
./deploy_watchlist_fix.sh
```

### Opción 2: Deploy Manual

```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform

# 1. Pull latest code
git pull origin main

# 2. Build backend with new changes
docker compose --profile aws build --no-cache backend-aws

# 3. Restart backend service
docker compose --profile aws up -d backend-aws

# 4. Wait for service to start
sleep 15

# 5. Verify deployment
docker compose --profile aws ps backend-aws
```

## Verificación Post-Deploy

### 1. Verificar que el fix está desplegado

```bash
docker compose --profile aws exec backend-aws python3 << 'EOF'
from app.api.routes_dashboard import _serialize_watchlist_item
import inspect
source = inspect.getsource(_serialize_watchlist_item)
if 'default_sl_tp_mode' in source:
    print("✅ Fix deployed successfully!")
else:
    print("❌ Fix not found")
EOF
```

### 2. Verificar logs para advertencias de MarketData

```bash
docker compose --profile aws logs backend-aws | grep "MarketData missing fields" | tail -20
```

### 3. Verificar estado de MarketData

```bash
docker compose --profile aws exec backend-aws python3 scripts/verify_market_data_status.py
```

### 4. Probar API de watchlist

```bash
# Verificar que los campos tienen valores por defecto
curl -s http://localhost:8002/api/watchlist | jq '.[0] | {symbol, sl_tp_mode, order_status, exchange}' | head -10
```

## Impacto Esperado

Después del deploy:

1. ✅ Los campos `sl_tp_mode`, `order_status`, y `exchange` siempre tendrán valores (no más `-`)
2. ✅ Los logs mostrarán advertencias cuando MarketData esté ausente o incompleto
3. ✅ Más fácil identificar cuándo `market_updater` necesita atención

## Campos Restantes (price, rsi, ma50, ma200, ema10)

Estos campos **aún pueden mostrar `-`** si `MarketData` está vacío o desactualizado. Para resolverlos completamente:

1. **Asegurar que `market_updater` esté corriendo:**
   ```bash
   docker compose --profile aws ps market-updater-aws
   docker compose --profile aws logs market-updater-aws --tail=50
   ```

2. **Si no está corriendo, iniciarlo:**
   ```bash
   docker compose --profile aws up -d market-updater-aws
   ```

3. **Ver instrucciones completas en:** `VERIFY_MARKET_DATA_INSTRUCTIONS.md`

## Rollback (si es necesario)

Si hay problemas, puedes hacer rollback:

```bash
cd /home/ubuntu/automated-trading-platform
git log --oneline -5  # Ver últimos commits
git checkout <commit-anterior>
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws up -d backend-aws
```

## Notas

- Este deploy **no requiere** reiniciar otros servicios
- El cambio es **backward compatible** - no rompe funcionalidad existente
- Los valores por defecto solo se aplican cuando los campos son `None`

