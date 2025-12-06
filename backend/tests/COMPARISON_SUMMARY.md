# Resumen: Comparación de Payloads TP/SL Auto vs Manual

## ✅ Estado Actual

### 1. Unificación de Código Python

**✅ COMPLETADO:** Ambos flujos (automático y manual) ahora usan las mismas funciones:
- `create_take_profit_order()` en `tp_sl_order_creator.py`
- `create_stop_loss_order()` en `tp_sl_order_creator.py`

**Test unitario confirmado:** `backend/tests/compare_payloads.py` verifica que ambos flujos pasan los mismos parámetros a `trade_client.place_take_profit_order()`.

**Resultado del test:**
```
✅ PAYLOADS MATCH! Both flows send identical parameters to the exchange.
  Matches: 7 (symbol, side, price, qty, trigger_price, entry_price, dry_run)
  Differences: 0
```

---

### 2. Logging HTTP Detallado

**✅ IMPLEMENTADO:** Logging completo de requests/responses HTTP con:
- Marcadores `[TP_ORDER][AUTO]` / `[TP_ORDER][MANUAL]`
- Marcadores `[SL_ORDER][AUTO]` / `[SL_ORDER][MANUAL]`
- Request ID único para emparejar request/response
- Payload JSON completo antes de enviar
- Response completa después de recibir

**Ubicación del código:**
- `backend/app/services/brokers/crypto_com_trade.py`:
  - `place_take_profit_order()` - líneas 2126-2151
  - `place_stop_loss_order()` - líneas 1525-1548
  - Variaciones de precisión SL - líneas 1609-1633

**Propagación de `source`:**
- `tp_sl_order_creator.py` → `trade_client.place_take_profit_order(source=source)`
- `tp_sl_order_creator.py` → `trade_client.place_stop_loss_order(source=source)`
- `exchange_sync.py` → `create_take_profit_order(source="auto")`
- `sl_tp_checker.py` → `create_take_profit_order(source="manual")`

---

## 📋 Próximos Pasos para el Usuario

### Paso 1: Prueba Real en la App

1. **Elige una moneda donde el TP automático haya funcionado:**
   - Por ejemplo: AKT_USDT, LDO_USDT, etc.
   - Verifica que hay una posición abierta

2. **Crea un TP manual para esa misma posición:**
   - Desde el dashboard: selecciona la moneda → crea TP manualmente
   - O desde Telegram: usa el menú de protección → selecciona moneda → crea TP

3. **Observa el resultado:**
   - ✅ Si funciona: El problema estaba en el código antiguo y ya está resuelto
   - ❌ Si falla con 229/40004: Continúa al Paso 2

---

### Paso 2: Extraer y Comparar Logs HTTP

#### 2.1 Extraer Logs

```bash
# Conectar al servidor AWS
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249

# Ver logs de TP automático
cd automated-trading-platform
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[AUTO\]" | tail -50

# Ver logs de TP manual
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[MANUAL\]" | tail -50

# Ver ambos
docker compose logs backend-aws 2>&1 | grep -E "\[TP_ORDER\]\[AUTO\]|\[TP_ORDER\]\[MANUAL\]" | tail -100
```

#### 2.2 Buscar Request ID Específico

Si encuentras un request_id en los logs, puedes ver toda la conversación:

```bash
# Ejemplo: buscar request_id "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
docker compose logs backend-aws 2>&1 | grep "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

#### 2.3 Comparar Payloads JSON

En los logs, busca las líneas que dicen:
```
[TP_ORDER][AUTO][REQUEST_ID] Sending HTTP request to exchange:
  Payload JSON: { ... }
```

Compara los campos clave:
- `params.instrument_name`
- `params.side`
- `params.type`
- `params.price`
- `params.quantity`
- `params.trigger_price`
- `params.ref_price`
- `params.trigger_condition`

#### 2.4 Comparar Responses

Busca las líneas que dicen:
```
[TP_ORDER][AUTO][REQUEST_ID] Received HTTP response from exchange:
  Status Code: 200 (o 4xx/5xx)
  Response Body: { ... }
```

Compara:
- Status Code: ¿200 (éxito) o error?
- Response Body: ¿Qué error específico devuelve el exchange?

---

### Paso 3: Análisis de Resultados

#### Si los Payloads JSON son Idénticos

**Pero el exchange responde diferente:**
- ✅ El código está correcto
- ❌ El problema está en el estado de la cuenta/posición
- **Solución:** Comparar:
  - Cantidad disponible en el momento AUTO vs MANUAL
  - Modo margin (si aplica)
  - Posiciones abiertas
  - Balance disponible

#### Si los Payloads JSON son Diferentes

**Hay diferencias en los campos:**
- ❌ El código está generando payloads distintos
- **Solución:** Identificar qué campo difiere y por qué
- **Causas comunes:**
  - Tipos de datos diferentes (string vs número)
  - Mayúsculas/minúsculas diferentes
  - Campos presentes en uno y ausentes en otro
  - Valores calculados diferentes (price, quantity, ref_price)

---

## 🔍 Ejemplo de Comparación

### Log AUTO (Éxito)
```
[TP_ORDER][AUTO][req-123] Sending HTTP request to exchange:
  Payload JSON: {
    "params": {
      "instrument_name": "AKT_USDT",
      "side": "SELL",
      "type": "TAKE_PROFIT_LIMIT",
      "price": "1.5632",
      "quantity": "6.5",
      "trigger_price": "1.5632",
      "ref_price": "1.5177",
      "trigger_condition": ">= 1.5632"
    }
  }

[TP_ORDER][AUTO][req-123] Received HTTP response from exchange:
  Status Code: 200
  Response Body: {
    "result": {
      "order_id": "5755600476554550077",
      "status": "OPEN"
    }
  }
```

### Log MANUAL (Fallo)
```
[TP_ORDER][MANUAL][req-456] Sending HTTP request to exchange:
  Payload JSON: {
    "params": {
      "instrument_name": "AKT_USDT",
      "side": "SELL",
      "type": "TAKE_PROFIT_LIMIT",
      "price": "1.5632",
      "quantity": "6.5",
      "trigger_price": "1.5632",
      "ref_price": "1.5177",
      "trigger_condition": ">= 1.5632"
    }
  }

[TP_ORDER][MANUAL][req-456] Received HTTP response from exchange:
  Status Code: 400
  Response Body: {
    "code": 229,
    "message": "INVALID_REF_PRICE"
  }
```

**Análisis:** Si los payloads son idénticos pero el exchange responde diferente, el problema NO está en nuestro código.

---

## 📁 Archivos Creados/Modificados

### Archivos Nuevos
1. `backend/tests/compare_payloads.py` - Test unitario para comparar payloads Python
2. `backend/tests/TP_SL_PAYLOAD_VERIFICATION.md` - Documentación de verificación
3. `backend/tests/extract_http_logs.sh` - Script para extraer logs HTTP
4. `backend/tests/HTTP_LOGGING_GUIDE.md` - Guía de uso del logging HTTP
5. `backend/tests/COMPARISON_SUMMARY.md` - Este archivo

### Archivos Modificados
1. `backend/app/services/brokers/crypto_com_trade.py`
   - Agregado parámetro `source` a `place_take_profit_order()`
   - Agregado parámetro `source` a `place_stop_loss_order()`
   - Agregado logging HTTP detallado con request_id

2. `backend/app/services/tp_sl_order_creator.py`
   - Propagación de `source` a `trade_client.place_take_profit_order()`
   - Propagación de `source` a `trade_client.place_stop_loss_order()`

---

## ✅ Checklist de Verificación

- [x] Test unitario confirma que ambos flujos pasan los mismos parámetros Python
- [x] Logging HTTP implementado con marcadores AUTO/MANUAL
- [x] Request ID único para emparejar request/response
- [x] Payload JSON completo registrado antes de enviar
- [x] Response completa registrada después de recibir
- [x] `source` propagado desde `tp_sl_order_creator.py` hasta `crypto_com_trade.py`
- [x] Scripts y documentación creados para extraer y comparar logs
- [ ] **PENDIENTE:** Usuario ejecuta prueba real y compara logs HTTP

---

## 🎯 Conclusión

**A nivel de código Python, ambos flujos están completamente unificados.**

El siguiente paso es verificar que los payloads HTTP reales enviados al exchange sean idénticos. Si lo son pero el exchange responde diferente, el problema está en el estado de la cuenta/posición, no en nuestro código.

**Siguiente acción:** Ejecutar una prueba manual desde el dashboard y comparar los logs HTTP con los del flujo automático.

