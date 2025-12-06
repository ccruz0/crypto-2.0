# Ejemplo: Crear Orden Manual BUY + SL/TP para SOL_USDT

## Información de la Alerta

- **Symbol:** SOL_USDT
- **Price:** $168.09
- **Signal:** BUY

## Cálculo de Parámetros

### Precio de Entrada
- **Entry Price:** $168.09

### Stop Loss (3% conservador)
- **SL Percentage:** 3%
- **SL Price:** 168.09 * 0.97 = **$163.05**

### Take Profit (3% conservador)
- **TP Percentage:** 3%
- **TP Price:** 168.09 * 1.03 = **$173.14**

### Cantidad
- **Amount USD:** Ejemplo $100
- **Quantity:** 100 / 168.09 = **0.595 SOL** (aproximadamente)

## Request al Endpoint

### Opción 1: Usando curl

```bash
curl -X POST http://localhost:8002/manual-trade/confirm \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "symbol": "SOL_USDT",
    "side": "BUY",
    "quantity": 0.595,
    "price": 168.09,
    "is_margin": false,
    "sl_percentage": 3.0,
    "tp_percentage": 3.0,
    "sl_tp_mode": "conservative"
  }'
```

### Opción 2: Usando Python

```python
import requests

url = "http://localhost:8002/manual-trade/confirm"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer YOUR_TOKEN"
}
data = {
    "symbol": "SOL_USDT",
    "side": "BUY",
    "quantity": 0.595,
    "price": 168.09,
    "is_margin": False,
    "sl_percentage": 3.0,
    "tp_percentage": 3.0,
    "sl_tp_mode": "conservative"
}

response = requests.post(url, json=data, headers=headers)
print(response.json())
```

### Opción 3: Desde el Dashboard (si está implementado)

Si hay una interfaz en el dashboard para crear órdenes manuales, usar:
- Symbol: SOL_USDT
- Side: BUY
- Price: 168.09
- Quantity: 0.595 (o el amount_usd equivalente)
- SL Percentage: 3%
- TP Percentage: 3%

## Revisar Logs de Referencia

Después de ejecutar la orden, revisar los logs para capturar los payloads exactos:

```bash
# Logs de referencia del flujo manual
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[REFERENCE\]" | tail -50

# Logs HTTP detallados de SL order
docker compose logs backend-aws 2>&1 | grep "\[SL_ORDER\]\[MANUAL\]" | tail -50

# Logs HTTP detallados de TP order
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[MANUAL\]" | tail -50
```

## Payloads Esperados

### STOP_LOSS Order
```json
{
  "instrument_name": "SOL_USDT",
  "type": "STOP_LIMIT",
  "side": "SELL",
  "price": "163.05",
  "quantity": "0.595",
  "trigger_price": "161.36",
  "ref_price": "168.09"
}
```

### TAKE_PROFIT Order
```json
{
  "instrument_name": "SOL_USDT",
  "type": "TAKE_PROFIT_LIMIT",
  "side": "SELL",
  "price": "173.14",
  "quantity": "0.595",
  "trigger_price": "173.14",
  "ref_price": "<calculated from market>",
  "trigger_condition": ">= 173.14"
}
```

## Verificar Resultados

1. **Revisar respuesta del endpoint:**
   - Debe incluir `main_order`, `sl_order`, `tp_order`
   - Verificar que no haya errores en `sl_order` o `tp_order`

2. **Revisar logs:**
   - Buscar `[TP_ORDER][REFERENCE]` para ver los parámetros
   - Buscar `[SL_ORDER][MANUAL]` y `[TP_ORDER][MANUAL]` para ver payloads HTTP completos
   - Verificar que `ref_price` sea correcto en ambos casos

3. **Comparar con lógica automática:**
   - Si hay órdenes automáticas que fallan, comparar los payloads
   - Identificar diferencias en `ref_price`, `side`, `trigger_price`, etc.

## Notas Importantes

⚠️ **IMPORTANTE:** 
- Si `LIVE_TRADING=false`, las órdenes se ejecutarán en modo `dry_run`
- Para órdenes reales, asegúrate de que `LIVE_TRADING=true` en el `.env`
- Verifica que tengas suficiente balance antes de crear órdenes reales

