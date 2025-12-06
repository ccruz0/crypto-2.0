# Guía de Diagnóstico: Fallos en Creación de SL/TP

## Problema Actual

Las órdenes BUY se crean y ejecutan correctamente, pero las órdenes SL/TP fallan con el mensaje:
> "Las órdenes SL/TP no se pudieron crear (posible error de formato de precio)"

## Cambios Implementados

### 1. Logging Mejorado
- ✅ Logs detallados de errores SL/TP en `exchange_sync.py`
- ✅ Logs HTTP completos con payloads en `crypto_com_trade.py`
- ✅ Mensajes de error más específicos en Telegram

### 2. Scripts de Diagnóstico
- ✅ `backend/tools/diagnose_sl_tp_failure.sh` - Diagnóstico completo
- ✅ `backend/tools/check_sl_tp_errors.sh` - Revisión de errores
- ✅ `backend/tools/extract_order_logs.py` - Extracción de logs específicos

## Cómo Diagnosticar el Problema

### Paso 1: Ejecutar el Script de Diagnóstico

En el servidor AWS, ejecuta:

```bash
docker compose exec backend-aws bash /app/tools/diagnose_sl_tp_failure.sh ORDER_ID SYMBOL
```

Ejemplo:
```bash
docker compose exec backend-aws bash /app/tools/diagnose_sl_tp_failure.sh 5755600477880747933 SOL_USDT
```

### Paso 2: Revisar Logs Manualmente

Si prefieres revisar los logs manualmente:

```bash
# Ver intentos de creación de SL/TP
docker compose logs backend-aws 2>&1 | grep -A 30 "Creating SL/TP for SOL_USDT" | tail -50

# Ver errores específicos
docker compose logs backend-aws 2>&1 | grep -E "❌.*SL.*failed|❌.*TP.*failed|BOTH SL/TP orders failed" | tail -30

# Ver logs HTTP de SL
docker compose logs backend-aws 2>&1 | grep "\[SL_ORDER\]" | tail -50

# Ver logs HTTP de TP
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]" | tail -50

# Ver errores de código específico
docker compose logs backend-aws 2>&1 | grep -E "error.*229|error.*40004|error.*220|error.*308" | tail -30
```

### Paso 3: Identificar el Error Específico

Busca en los logs uno de estos errores comunes:

#### Error 229: INVALID_REF_PRICE
- **Causa:** `ref_price` no está en el lado correcto del mercado
- **Solución:** `ref_price` debe ser:
  - Para `side=SELL`: `ref_price < precio_mercado_actual`
  - Para `side=BUY`: `ref_price > precio_mercado_actual`

#### Error 40004: Missing or invalid argument
- **Causa:** Falta un campo requerido o el formato es incorrecto
- **Solución:** Verificar que todos los campos requeridos estén presentes y con el formato correcto

#### Error 220: INVALID_SIDE
- **Causa:** El `side` no corresponde al sentido correcto de la posición
- **Solución:** Para posición LONG (BUY), TP/SL deben tener `side=SELL`

#### Error 308: Invalid price format
- **Causa:** El formato del precio no cumple con los requisitos del exchange
- **Solución:** Ajustar la precisión decimal según el instrumento

## Qué Buscar en los Logs

### 1. Parámetros Usados
Busca en los logs:
```
Parameters used:
  - Symbol: SOL_USDT
  - Side: BUY (original order side)
  - Entry Price: 167.23
  - Filled Quantity: 0.059
  - SL Price: 162.21
  - TP Price: 172.25
```

### 2. Payloads HTTP
Busca los payloads completos enviados al exchange:
```
[SL_ORDER][AUTO][request_id] Payload JSON: {...}
[TP_ORDER][AUTO][request_id] Payload JSON: {...}
```

### 3. Respuestas del Exchange
Busca las respuestas del exchange:
```
[SL_ORDER][AUTO][request_id] Status Code: 400
[SL_ORDER][AUTO][request_id] Response Body: {"code": 229, "message": "INVALID_REF_PRICE"}
```

## Próximos Pasos

1. **Ejecuta el diagnóstico** con el script proporcionado
2. **Comparte los logs** del error específico (código de error y payload)
3. **Ajustaremos la lógica** según el error específico encontrado

## Notas Importantes

- Los logs HTTP ahora incluyen `[SL_ORDER][AUTO]` y `[TP_ORDER][AUTO]` para fácil identificación
- Los errores ahora se muestran con más detalle en Telegram
- El código ya maneja la inversión correcta del `side` (BUY → SELL para TP/SL)
- El `ref_price` se calcula dinámicamente desde el precio de mercado actual

## Comparación con Flujo de Referencia

El flujo automático ahora usa las mismas funciones que el flujo manual de referencia:
- `create_stop_loss_order()` - Misma lógica que flujo manual
- `create_take_profit_order()` - Misma lógica que flujo manual
- Mismos parámetros: `entry_price`, `side` invertido, etc.

Si el flujo manual funciona pero el automático no, la diferencia debe estar en:
1. Los valores de los parámetros (precios, cantidades)
2. El estado de la cuenta/exchange en el momento de la creación
3. Timing (el precio de mercado puede haber cambiado)

