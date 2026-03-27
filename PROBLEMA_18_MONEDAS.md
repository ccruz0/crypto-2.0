# Problema: Solo se Ven 18 Monedas en el Dashboard

## 🔍 Análisis del Problema

### Estado Actual:
- **32 monedas** en `watchlist_items` (base de datos)
- **25 monedas** en `MarketPrice` (tabla de precios)
- **18 monedas** visibles en el dashboard

### Causa Raíz:
El endpoint `/api/market/top-coins-data` solo devuelve monedas que están en la tabla `MarketPrice`. Si una moneda está en `watchlist_items` pero NO está en `MarketPrice`, no aparecerá en el dashboard.

### Diferencia:
- **32 monedas en watchlist** - **25 monedas en MarketPrice** = **7 monedas faltantes**
- **25 monedas en MarketPrice** - **18 monedas visibles** = **7 monedas no visibles**

Esto sugiere que:
1. 7 monedas están en `watchlist_items` pero no en `MarketPrice` (no tienen precio actualizado)
2. Posiblemente algunas monedas en `MarketPrice` tienen precio = 0 y se están filtrando

## ✅ Solución

### Opción 1: Asegurar que todas las monedas del watchlist estén en MarketPrice

El proceso `market_updater.py` debería actualizar los precios de todas las monedas en el watchlist. Verificar que esté corriendo:

```bash
# En el servidor AWS
cd ~/crypto-2.0
docker compose --profile aws ps market-updater
```

### Opción 2: Modificar el endpoint para incluir monedas del watchlist aunque no estén en MarketPrice

Modificar `/api/market/top-coins-data` para que también incluya monedas de `watchlist_items` que no estén en `MarketPrice`, mostrándolas con precio 0 o "N/A".

### Opción 3: Verificar si hay filtros en el frontend

El frontend tiene `WATCHLIST_PAGE_SIZE = 30`, así que debería mostrar hasta 30 monedas. Si solo muestra 18, podría ser que:
- El endpoint solo devuelve 18 monedas
- Hay algún filtro adicional que oculta monedas sin precio

## 🔧 Verificación Rápida

Para verificar qué está pasando, ejecuta en el servidor AWS:

```bash
cd ~/crypto-2.0
docker compose --profile aws exec backend-aws python3 /app/check_db_direct.py
```

Esto mostrará todas las monedas en `watchlist_items` con su estado de `trade_enabled`.

Luego verifica qué devuelve el endpoint:

```bash
curl -H "x-api-key: demo-key" http://175.41.189.249:8002/api/market/top-coins-data | python3 -m json.tool | grep -c "instrument_name"
```

## 📝 Nota Importante

Las monedas que están en `watchlist_items` pero NO en `MarketPrice` no aparecerán en el dashboard porque el endpoint `/api/market/top-coins-data` solo devuelve monedas con precios actualizados.

Para que todas las 32 monedas aparezcan:
1. Asegurar que `market_updater.py` esté corriendo y actualizando todas las monedas del watchlist
2. O modificar el endpoint para incluir monedas del watchlist aunque no tengan precio en MarketPrice

