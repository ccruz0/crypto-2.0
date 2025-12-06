# Guía de Logging HTTP para TP/SL Orders

## Resumen

Se ha implementado logging HTTP detallado para comparar los payloads reales que se envían al exchange en los flujos automático y manual.

---

## 1. Logging Implementado

### Marcadores de Log

Todos los logs HTTP para órdenes TP/SL incluyen:
- `[TP_ORDER][AUTO]` o `[TP_ORDER][MANUAL]` para Take Profit
- `[SL_ORDER][AUTO]` o `[SL_ORDER][MANUAL]` para Stop Loss
- `[REQUEST_ID]` único para emparejar request/response

### Información Registrada

**Antes de enviar la request:**
- URL completa
- Método HTTP (POST)
- Source (AUTO o MANUAL)
- Payload JSON completo (formateado)

**Después de recibir la response:**
- Request ID (para emparejar con la request)
- Status Code HTTP
- Response Body completo (JSON formateado o texto)

---

## 2. Cómo Extraer los Logs

### Opción 1: Script Automático

```bash
# Ver logs de ambos flujos
docker compose exec backend-aws bash /app/tests/extract_http_logs.sh BOTH

# Solo logs automáticos
docker compose exec backend-aws bash /app/tests/extract_http_logs.sh AUTO

# Solo logs manuales
docker compose exec backend-aws bash /app/tests/extract_http_logs.sh MANUAL
```

### Opción 2: Comandos Manuales

```bash
# Ver todos los logs de TP automático
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[AUTO\]"

# Ver todos los logs de TP manual
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[MANUAL\]"

# Ver logs de un request_id específico
docker compose logs backend-aws 2>&1 | grep "REQUEST_ID_AQUI"

# Ver últimos 100 logs de TP/SL
docker compose logs backend-aws --tail 100 2>&1 | grep -E "\[TP_ORDER\]|\[SL_ORDER\]"
```

---

## 3. Comparar Payloads AUTO vs MANUAL

### Paso 1: Ejecutar Casos de Prueba

1. **Caso AUTOMÁTICO:**
   - Espera a que se ejecute una orden BUY automática
   - O fuerza una ejecución desde el dashboard
   - El sistema creará TP/SL automáticamente

2. **Caso MANUAL:**
   - Desde el dashboard, crea una orden TP manual para la misma moneda/posición
   - O usa el comando de Telegram para crear TP/SL manualmente

### Paso 2: Extraer los Logs

```bash
# Extraer logs de ambos flujos
docker compose logs backend-aws 2>&1 | grep -E "\[TP_ORDER\]\[AUTO\]|\[TP_ORDER\]\[MANUAL\]" > /tmp/tp_logs.txt

# Ver el archivo
cat /tmp/tp_logs.txt
```

### Paso 3: Comparar los Payloads

Busca en los logs:
1. `[TP_ORDER][AUTO][REQUEST_ID] Sending HTTP request`
2. `[TP_ORDER][MANUAL][REQUEST_ID] Sending HTTP request`

Compara los campos del `Payload JSON`:
- `instrument_name` / `symbol`
- `side`
- `type` / `order_type`
- `price`
- `quantity`
- `trigger_price`
- `ref_price`
- `trigger_condition`
- `time_in_force`
- Cualquier otro campo

### Paso 4: Verificar las Responses

Busca las responses correspondientes:
1. `[TP_ORDER][AUTO][REQUEST_ID] Received HTTP response`
2. `[TP_ORDER][MANUAL][REQUEST_ID] Received HTTP response`

Compara:
- `Status Code`: ¿200 (éxito) o 4xx/5xx (error)?
- `Response Body`: ¿Qué error específico devuelve el exchange?

---

## 4. Ejemplo de Log Esperado

```
[TP_ORDER][AUTO][a1b2c3d4-e5f6-7890-abcd-ef1234567890] Sending HTTP request to exchange:
  URL: https://api.crypto.com/exchange/v1/private/create-order
  Method: POST
  Source: auto
  Payload JSON: {
    "id": 1,
    "method": "private/create-order",
    "api_key": "...",
    "params": {
      "instrument_name": "AKT_USDT",
      "side": "SELL",
      "type": "TAKE_PROFIT_LIMIT",
      "price": "1.5632",
      "quantity": "6.5",
      "trigger_price": "1.5632",
      "ref_price": "1.5177",
      "trigger_condition": ">= 1.5632"
    },
    "sig": "...",
    "nonce": 1234567890
  }

[TP_ORDER][AUTO][a1b2c3d4-e5f6-7890-abcd-ef1234567890] Received HTTP response from exchange:
  Status Code: 200
  Response Body: {
    "id": 1,
    "result": {
      "order_id": "5755600476554550077",
      "client_order_id": "...",
      "status": "OPEN"
    }
  }
```

---

## 5. Qué Buscar en la Comparación

### Si los Payloads son Idénticos

Si los payloads JSON son idénticos pero el exchange responde diferente:
- **Posible causa:** Estado diferente de la cuenta/posición
- **Solución:** Comparar el contexto (cantidad disponible, modo margin, etc.) en el momento de cada request

### Si los Payloads son Diferentes

Si hay diferencias en los payloads:
- **Causa:** El código está generando payloads distintos
- **Solución:** Revisar la lógica que genera los payloads y unificarla

### Diferencias Comunes a Verificar

1. **Tipos de datos:**
   - `"1.5632"` (string) vs `1.5632` (número)
   - `"SELL"` vs `"sell"` (mayúsculas/minúsculas)

2. **Campos presentes/ausentes:**
   - `ref_price` presente en uno y ausente en otro
   - `trigger_condition` con formato diferente

3. **Valores diferentes:**
   - `price` diferente entre AUTO y MANUAL
   - `quantity` diferente
   - `entry_price` / `ref_price` diferente

---

## 6. Verificar Estado de la Cuenta

Si los payloads son idénticos pero el exchange responde diferente, verifica:

```bash
# Ver balance disponible
docker compose exec backend-aws python3 -c "
from app.services.brokers.crypto_com_trade import trade_client
balance = trade_client.get_account_summary()
print(balance)
"

# Ver posiciones abiertas
docker compose exec backend-aws python3 -c "
from app.services.brokers.crypto_com_trade import trade_client
positions = trade_client.get_open_positions()
print(positions)
"
```

Compara estos valores entre el momento AUTO y el momento MANUAL.

---

## 7. Próximos Pasos

1. ✅ Ejecutar caso AUTOMÁTICO y extraer logs
2. ✅ Ejecutar caso MANUAL y extraer logs
3. ✅ Comparar payloads JSON campo por campo
4. ✅ Comparar responses del exchange
5. ✅ Si hay diferencias, identificar la causa y corregirla
6. ✅ Si no hay diferencias pero el exchange responde diferente, investigar estado de cuenta/posición

---

**Fecha de implementación:** $(date)
**Archivos modificados:**
- `backend/app/services/brokers/crypto_com_trade.py` (logging HTTP en `place_take_profit_order` y `place_stop_loss_order`)
- `backend/app/services/tp_sl_order_creator.py` (propagación de `source`)

