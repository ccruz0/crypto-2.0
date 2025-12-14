# Fix: BTC_USDT no está visible en watchlist

## Problema

BTC_USDT no aparece en la watchlist aunque debería estar visible.

## Causa

El problema más común es que BTC_USDT está marcado como eliminado (`is_deleted = True`) en la base de datos. El endpoint `/api/dashboard` filtra automáticamente los elementos con `is_deleted = True`, por lo que no aparecen en la watchlist.

## Solución

### Opción 1: Usar el script de restauración (Recomendado)

Ejecuta el script de restauración que verifica y restaura BTC_USDT:

```bash
# Asegúrate de que el servidor API esté corriendo
export API_URL="http://tu-servidor:8000/api"  # Ajusta según tu configuración
export API_KEY="tu-api-key"  # Ajusta según tu configuración

python3 fix_btc_usdt_watchlist.py
```

El script:
1. Verifica si BTC_USDT existe en la base de datos
2. Si existe pero está eliminado, lo restaura automáticamente
3. Si no existe, crea una nueva entrada
4. Verifica que ahora esté visible en la watchlist

### Opción 2: Usar el nuevo endpoint REST

Se ha agregado un nuevo endpoint para restaurar elementos por símbolo:

```bash
# Restaurar BTC_USDT
curl -X PUT "http://tu-servidor:8000/api/dashboard/symbol/BTC_USDT/restore" \
  -H "X-API-Key: tu-api-key" \
  -H "Content-Type: application/json"
```

### Opción 3: Actualizar manualmente vía API

Si conoces el ID del elemento:

```bash
# Obtener el elemento (incluye elementos eliminados)
curl "http://tu-servidor:8000/api/dashboard/symbol/BTC_USDT" \
  -H "X-API-Key: tu-api-key"

# Restaurar usando el ID
curl -X PUT "http://tu-servidor:8000/api/dashboard/{item_id}" \
  -H "X-API-Key: tu-api-key" \
  -H "Content-Type: application/json" \
  -d '{"is_deleted": false}'
```

### Opción 4: Crear nuevo elemento si no existe

Si BTC_USDT no existe en absoluto:

```bash
curl -X POST "http://tu-servidor:8000/api/dashboard" \
  -H "X-API-Key: tu-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC_USDT",
    "exchange": "CRYPTO_COM",
    "alert_enabled": false,
    "trade_enabled": false,
    "is_deleted": false
  }'
```

## Verificación

Después de restaurar, verifica que BTC_USDT esté visible:

```bash
# Listar todos los elementos activos de la watchlist
curl "http://tu-servidor:8000/api/dashboard" \
  -H "X-API-Key: tu-api-key" | jq '.[] | select(.symbol == "BTC_USDT")'
```

O simplemente revisa la interfaz web - BTC_USDT debería aparecer en la pestaña "Watchlist".

## Endpoints relacionados

- `GET /api/dashboard` - Lista todos los elementos activos (filtra `is_deleted = False`)
- `GET /api/dashboard/symbol/{symbol}` - Obtiene un elemento por símbolo (incluye eliminados)
- `PUT /api/dashboard/symbol/{symbol}/restore` - Restaura un elemento eliminado por símbolo
- `PUT /api/dashboard/{item_id}` - Actualiza un elemento por ID (puede restaurar con `is_deleted: false`)
- `POST /api/dashboard` - Crea un nuevo elemento en la watchlist

## Notas

- El endpoint `/api/dashboard` siempre filtra elementos con `is_deleted = True`
- El endpoint `/api/dashboard/symbol/{symbol}` NO filtra, por lo que puede devolver elementos eliminados
- La restauración solo funciona si la base de datos soporta soft delete (columna `is_deleted`)


