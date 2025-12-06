# Flujo de Referencia: BUY Manual + SL/TP Automático

## Ubicación

**Archivo:** `backend/app/api/routes_manual_trade.py`  
**Endpoint:** `POST /manual-trade/confirm`

## Descripción

Este endpoint implementa el **flujo de referencia dorada** para crear órdenes BUY manuales con Stop Loss y Take Profit automáticos. Este flujo funciona correctamente y debe usarse como referencia para corregir la lógica automática.

## Flujo Completo

1. **Crea una orden BUY LIMIT** (orden de entrada)
2. **Crea automáticamente una orden STOP_LOSS** (tipo `STOP_LIMIT`)
3. **Crea automáticamente una orden TAKE_PROFIT** (tipo `TAKE_PROFIT_LIMIT`)

## Formato de Payloads que Funcionan

### STOP_LOSS (STOP_LIMIT)

```json
{
  "instrument_name": "AKT_USDT",
  "type": "STOP_LIMIT",
  "side": "SELL",  // Invertido desde entrada BUY (UPPERCASE requerido)
  "price": "1.4500",  // Precio de ejecución SL
  "quantity": "6.5",
  "trigger_price": "1.4355",  // Precio trigger (SL * 0.99 para BUY entry)
  "ref_price": "1.5177",  // CRÍTICO: Precio de entrada (precio de la orden BUY original)
  "client_oid": "uuid-optional",
  "time_in_force": "GOOD_TILL_CANCEL"  // Opcional
}
```

**Campos Críticos:**
- `ref_price`: **DEBE ser el precio de entrada** (precio de la orden BUY original)
- `side`: **DEBE ser UPPERCASE** ("SELL" para entrada BUY, "BUY" para entrada SELL)
- `trigger_price`: Generalmente `SL_price * 0.99` para entrada BUY, `SL_price * 1.01` para entrada SELL

### TAKE_PROFIT (TAKE_PROFIT_LIMIT)

```json
{
  "instrument_name": "AKT_USDT",
  "type": "TAKE_PROFIT_LIMIT",
  "side": "SELL",  // Invertido desde entrada BUY (UPPERCASE requerido)
  "price": "1.5632",  // Precio de ejecución TP
  "quantity": "6.5",
  "trigger_price": "1.5632",  // DEBE ser igual a price para TAKE_PROFIT_LIMIT
  "ref_price": "0.64",  // Calculado dinámicamente desde precio de mercado
  "trigger_condition": ">= 1.5632",  // Condición de activación
  "client_oid": "uuid-optional",
  "time_in_force": "GOOD_TILL_CANCEL"  // Opcional
}
```

**Campos Críticos:**
- `ref_price`: **Se calcula dinámicamente** desde el precio de mercado actual
  - Para `side=SELL`: `ref_price` debe ser **< precio de mercado** (usualmente `min(tp_price, market_price * 0.995)`)
  - Para `side=BUY`: `ref_price` debe ser **> precio de mercado** (usualmente `max(tp_price, market_price * 1.005)`)
- `trigger_price`: **DEBE ser igual a `price`** (ambos son el precio TP)
- `trigger_condition`: Formato `">= {TP_price}"` donde TP_price es el precio TP
- `side`: **DEBE ser UPPERCASE** ("SELL" para entrada BUY, "BUY" para entrada SELL)

## Diferencias Clave con la Lógica Actual

### ✅ Lo que hace BIEN el flujo manual:

1. **Pasa `entry_price` explícitamente** a `place_stop_loss_order` y `place_take_profit_order`
2. **Calcula `ref_price` correctamente**:
   - Para SL: usa `entry_price` (precio de entrada)
   - Para TP: calcula desde precio de mercado actual
3. **Invierte el `side` correctamente**: BUY entry → SELL para SL/TP
4. **Usa `trigger_price` correcto**:
   - Para SL: `SL_price * 0.99` (para BUY entry)
   - Para TP: igual a `price` (ambos son TP price)

### ❌ Lo que puede estar mal en la lógica automática:

1. **No pasa `entry_price`** o lo pasa incorrectamente
2. **`ref_price` calculado incorrectamente**:
   - Para SL: no usa `entry_price`
   - Para TP: no respeta la relación con precio de mercado
3. **`side` incorrecto**: no invierte desde entrada o usa formato incorrecto
4. **`trigger_price` incorrecto**: no igual a `price` para TP

## Logs de Referencia

El flujo manual ahora incluye logs detallados con el prefijo `[TP_ORDER][REFERENCE]`:

```
[TP_ORDER][REFERENCE] BUY order created:
[TP_ORDER][REFERENCE]   symbol: AKT_USDT
[TP_ORDER][REFERENCE]   side: BUY
[TP_ORDER][REFERENCE]   price: 1.5177
[TP_ORDER][REFERENCE]   quantity: 6.5
[TP_ORDER][REFERENCE]   order_id: 123456789

[TP_ORDER][REFERENCE] Creating STOP_LOSS order:
[TP_ORDER][REFERENCE]   symbol: AKT_USDT
[TP_ORDER][REFERENCE]   side: SELL (inverted from entry)
[TP_ORDER][REFERENCE]   price: 1.4500 (SL execution price)
[TP_ORDER][REFERENCE]   quantity: 6.5
[TP_ORDER][REFERENCE]   trigger_price: 1.4355
[TP_ORDER][REFERENCE]   entry_price: 1.5177 (for ref_price)

[TP_ORDER][REFERENCE] Creating TAKE_PROFIT order:
[TP_ORDER][REFERENCE]   symbol: AKT_USDT
[TP_ORDER][REFERENCE]   side: SELL (inverted from entry)
[TP_ORDER][REFERENCE]   price: 1.5632 (TP execution price)
[TP_ORDER][REFERENCE]   quantity: 6.5
[TP_ORDER][REFERENCE]   entry_price: 1.5177 (for ref_price calculation)
```

Además, los logs HTTP detallados en `crypto_com_trade.py` capturan los payloads completos:

```
[SL_ORDER][MANUAL][request_id] Sending HTTP request to exchange:
  URL: https://api.crypto.com/v2/private/create-order
  Method: POST
  Source: manual
  Payload JSON: {...}

[TP_ORDER][MANUAL][request_id] Sending HTTP request to exchange:
  URL: https://api.crypto.com/v2/private/create-order
  Method: POST
  Source: manual
  Payload JSON: {...}
```

## Cómo Usar Esta Referencia

1. **Ejecutar el flujo manual** desde el dashboard o API:
   ```bash
   POST /manual-trade/confirm
   {
     "symbol": "AKT_USDT",
     "side": "BUY",
     "quantity": 6.5,
     "price": 1.5177,
     "sl_percentage": 3.0,
     "tp_percentage": 3.0
   }
   ```

2. **Revisar los logs** para capturar los payloads exactos:
   ```bash
   docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[REFERENCE\]" | tail -50
   docker compose logs backend-aws 2>&1 | grep "\[SL_ORDER\]\[MANUAL\]" | tail -50
   docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[MANUAL\]" | tail -50
   ```

3. **Comparar con los payloads de la lógica automática**:
   ```bash
   docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[AUTO\]" | tail -50
   ```

4. **Ajustar la lógica automática** en:
   - `backend/app/services/tp_sl_order_creator.py`
   - `backend/app/services/exchange_sync.py`
   - `backend/app/services/sl_tp_checker.py`

   Para que construya los payloads exactamente igual que el flujo manual.

## Próximos Pasos

1. ✅ Documentación del flujo de referencia creada
2. ✅ Logs de referencia añadidos al flujo manual
3. ✅ `entry_price` ahora se pasa explícitamente
4. ⏳ Ejecutar flujo manual y capturar payloads exitosos
5. ⏳ Comparar payloads manuales vs automáticos
6. ⏳ Ajustar lógica automática para que coincida con flujo manual

