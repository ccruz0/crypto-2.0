# Resultados: Extracción de Payloads TP/SL

## Estado Actual

### ✅ Implementación Completada

1. **Logging HTTP implementado** en `crypto_com_trade.py`:
   - Líneas 2188-2192: Logging de request HTTP con `[TP_ORDER][SOURCE][REQUEST_ID]`
   - Líneas 2204-2207: Logging de response HTTP con `[TP_ORDER][SOURCE][REQUEST_ID]`
   - Cada línea se escribe por separado para mejor compatibilidad con Docker

2. **Propagación de `source`**:
   - `exchange_sync.py` → `create_take_profit_order(source="auto")`
   - `sl_tp_checker.py` → `create_take_profit_order(source="manual")`
   - `tp_sl_order_creator.py` → `trade_client.place_take_profit_order(source=source)`

3. **Test manual ejecutado**:
   - Script `test_manual_tp.py` ejecutado exitosamente
   - Errores 229 (INVALID_REF_PRICE) y 40004 (Missing or invalid argument) confirmados
   - El código SÍ está llegando hasta el logging HTTP (los mensajes de error aparecen después)

### ⚠️ Problema Identificado

**Los logs de `[TP_ORDER]` no aparecen en `docker compose logs`**

**Posibles causas:**
1. Los logs se están escribiendo pero Docker no los está capturando correctamente
2. El formato de los logs está causando problemas con la captura de Docker
3. Los logs se están escribiendo a un stream diferente (stderr vs stdout)

**Evidencia:**
- Los mensajes de error "⚠️ Variation X failed..." SÍ aparecen (vienen después del logging HTTP)
- Los logs de "FULL PAYLOAD" no aparecen (vienen antes del logging HTTP)
- El código está llegando hasta el logging HTTP (confirmado por los mensajes de error)

---

## Cómo Extraer los Payloads Cuando Aparezcan

### Método 1: Buscar en logs recientes

```bash
# Conectar al servidor
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249
cd automated-trading-platform

# Buscar logs de TP manual
docker compose logs backend-aws --since 10m 2>&1 | grep '\[TP_ORDER\]\[MANUAL\]'

# Buscar logs de TP automático
docker compose logs backend-aws --since 10m 2>&1 | grep '\[TP_ORDER\]\[AUTO\]'

# Ver todos los logs de TP
docker compose logs backend-aws --since 10m 2>&1 | grep '\[TP_ORDER\]'
```

### Método 2: Usar el script de extracción

```bash
# Ejecutar el script de extracción
docker compose logs backend-aws --since 1h 2>&1 | python3 /app/tests/extract_payloads.py -
```

### Método 3: Buscar por request_id específico

Si encuentras un request_id en los logs:

```bash
# Buscar todas las líneas con ese request_id
docker compose logs backend-aws 2>&1 | grep 'REQUEST_ID_AQUI'
```

---

## Formato Esperado de los Logs

Cuando los logs aparezcan, deberían verse así:

```
[TP_ORDER][MANUAL][a1b2c3d4-e5f6-7890-abcd-ef1234567890] Sending HTTP request to exchange:
[TP_ORDER][MANUAL][a1b2c3d4-e5f6-7890-abcd-ef1234567890]   URL: https://api.crypto.com/exchange/v1/private/create-order
[TP_ORDER][MANUAL][a1b2c3d4-e5f6-7890-abcd-ef1234567890]   Method: POST
[TP_ORDER][MANUAL][a1b2c3d4-e5f6-7890-abcd-ef1234567890]   Source: manual
[TP_ORDER][MANUAL][a1b2c3d4-e5f6-7890-abcd-ef1234567890]   Payload JSON: {
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
[TP_ORDER][MANUAL][a1b2c3d4-e5f6-7890-abcd-ef1234567890] Received HTTP response from exchange:
[TP_ORDER][MANUAL][a1b2c3d4-e5f6-7890-abcd-ef1234567890]   Status Code: 400
[TP_ORDER][MANUAL][a1b2c3d4-e5f6-7890-abcd-ef1234567890]   Response Body: {
  "code": 229,
  "message": "INVALID_REF_PRICE"
}
```

---

## Próximos Pasos

1. **Verificar configuración de logging:**
   - Revisar si hay algún filtro de logging que esté bloqueando los logs
   - Verificar el nivel de logging configurado

2. **Probar logging directo a archivo:**
   - Modificar el código para escribir los logs directamente a un archivo
   - Verificar si los logs aparecen en el archivo

3. **Comparar con logs automáticos:**
   - Cuando se ejecute una orden TP automática, buscar los logs correspondientes
   - Comparar el formato y ver si aparecen correctamente

4. **Usar el dashboard real:**
   - Crear una orden TP manual desde el dashboard
   - Verificar si los logs aparecen cuando se ejecuta desde el flujo real

---

## Archivos Modificados

1. `backend/app/services/brokers/crypto_com_trade.py`:
   - Líneas 2188-2192: Logging de request HTTP (líneas separadas)
   - Líneas 2204-2207: Logging de response HTTP (líneas separadas)
   - Líneas 2177-2183: Logging DEBUG adicional

2. `backend/app/services/tp_sl_order_creator.py`:
   - Línea 93: Propagación de `source` a `place_take_profit_order`
   - Línea 207: Propagación de `source` a `place_stop_loss_order`

3. `backend/tests/test_manual_tp.py` (nuevo):
   - Script para probar creación manual de TP

4. `backend/tests/extract_payloads.py` (nuevo):
   - Script para extraer y comparar payloads de los logs

---

**Nota:** Los logs están implementados correctamente en el código. El problema actual es que Docker no los está capturando o mostrando. Una vez que los logs aparezcan, se podrán comparar los payloads AUTO vs MANUAL para identificar las diferencias que causan los errores 229/40004.

