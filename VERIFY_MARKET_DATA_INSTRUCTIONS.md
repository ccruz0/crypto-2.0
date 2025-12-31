# Instrucciones para Verificar MarketData

Este documento explica cómo verificar el estado de MarketData y el proceso `market_updater`.

## Problema

Los campos técnicos (price, rsi, ma50, ma200, ema10) aparecen como `-` (None) en el frontend porque `MarketData` está vacío o desactualizado. Estos valores son calculados y guardados por el proceso `market_updater`.

## Verificación

### Opción 1: Script Automático (Recomendado)

Ejecuta el script de verificación:

**En el servidor AWS:**
```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
docker compose exec backend-aws python3 scripts/verify_market_data_status.py
```

**O desde local (si tienes acceso al servidor):**
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose exec backend-aws python3 scripts/verify_market_data_status.py"
```

Este script mostrará:
- Total de entradas en MarketData
- Entradas actualizadas en la última hora
- Entradas desactualizadas (> 2 horas)
- Ejemplos de entradas con sus indicadores
- Símbolos de watchlist que tienen/d no tienen MarketData

### Opción 2: Verificación Manual

#### 1. Verificar que market_updater está corriendo

```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform

# Verificar estado del contenedor
docker compose ps market-updater-aws

# Debería mostrar "Up" si está corriendo
```

Si no está corriendo:
```bash
# Iniciar el contenedor
docker compose up -d market-updater-aws

# Ver logs para verificar que está funcionando
docker compose logs market-updater-aws --tail=50 --follow
```

#### 2. Revisar logs del market_updater

```bash
# Ver últimos logs
docker compose logs market-updater-aws --tail=100

# Ver logs en tiempo real
docker compose logs market-updater-aws --follow

# Buscar errores
docker compose logs market-updater-aws | grep -i error
```

**Logs esperados:**
- `Starting market data update with technical indicators`
- `Found X non-deleted watchlist items`
- `Successfully updated MarketData for X symbols`
- Actualización cada 60 segundos

#### 3. Revisar logs del backend para advertencias

```bash
# Buscar advertencias sobre MarketData faltante
docker compose logs backend-aws | grep "MarketData missing fields"

# Ver últimas advertencias
docker compose logs backend-aws | grep "MarketData missing fields" | tail -20
```

#### 4. Verificar MarketData en la base de datos

```bash
# Ejecutar consulta directa
docker compose exec backend-aws python3 << 'EOF'
from app.database import SessionLocal
from app.models.market_price import MarketData
from datetime import datetime, timedelta, timezone

db = SessionLocal()
try:
    total = db.query(MarketData).count()
    print(f"Total MarketData entries: {total}")
    
    # Check recent updates
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = db.query(MarketData).filter(MarketData.updated_at >= one_hour_ago).count()
    print(f"Updated in last hour: {recent}")
    
    # Sample entries
    samples = db.query(MarketData).limit(5).all()
    for md in samples:
        print(f"{md.symbol}: price={md.price}, rsi={md.rsi}, updated={md.updated_at}")
finally:
    db.close()
EOF
```

#### 5. Verificar cobertura de watchlist

```bash
docker compose exec backend-aws python3 << 'EOF'
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketData

db = SessionLocal()
try:
    watchlist = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).all()
    print(f"Watchlist items: {len(watchlist)}")
    
    with_data = 0
    without_data = 0
    
    for item in watchlist:
        md = db.query(MarketData).filter(MarketData.symbol == item.symbol.upper()).first()
        if md and md.price:
            with_data += 1
        else:
            without_data += 1
            print(f"Missing: {item.symbol}")
    
    print(f"With MarketData: {with_data}")
    print(f"Without MarketData: {without_data}")
finally:
    db.close()
EOF
```

## Soluciones Comunes

### Problema: market_updater no está corriendo

**Solución:**
```bash
docker compose up -d market-updater-aws
docker compose logs market-updater-aws --follow
```

### Problema: market_updater tiene errores

**Revisar logs:**
```bash
docker compose logs market-updater-aws --tail=100 | grep -i error
```

**Errores comunes:**
- Error de conexión a base de datos → Verificar DATABASE_URL
- Error de conexión a APIs externas → Verificar red/proxy
- Rate limiting → Normal, el updater tiene delays incorporados

### Problema: MarketData existe pero está desactualizado

**Verificar última actualización:**
- El updater debería ejecutarse cada 60 segundos
- Si hay > 5 minutos sin actualización, verificar logs del updater

**Forzar actualización manual (testing):**
```bash
docker compose exec market-updater-aws python3 -c "
import asyncio
from market_updater import update_market_data
asyncio.run(update_market_data())
"
```

### Problema: MarketData tiene precio pero no indicadores (rsi, ma50, etc.)

**Causa:** Error al calcular indicadores técnicos (datos OHLCV insuficientes o API falló)

**Verificar:**
- Logs del updater para errores de cálculo
- Verificar que hay suficientes datos históricos (necesita ~200 candles para MA200)

## Estado Esperado

Después de que todo esté funcionando correctamente:

1. ✅ `market-updater-aws` contenedor está corriendo
2. ✅ Logs muestran actualizaciones cada 60 segundos
3. ✅ MarketData tiene entradas para todos los símbolos en watchlist
4. ✅ Todas las entradas tienen `updated_at` reciente (< 2 horas)
5. ✅ Todas las entradas tienen indicadores técnicos (rsi, ma50, ma200, ema10, atr)
6. ✅ No hay advertencias "MarketData missing fields" en logs del backend

## Monitoreo Continuo

Para monitorear el estado continuamente:

```bash
# Watch logs en tiempo real
docker compose logs -f market-updater-aws backend-aws | grep -E "MarketData|market.*update"

# O ejecutar el script de verificación periódicamente
watch -n 60 'docker compose exec backend-aws python3 scripts/verify_market_data_status.py'
```












