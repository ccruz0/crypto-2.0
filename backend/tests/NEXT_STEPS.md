# Próximos Pasos para Resolver SL/TP

## Estado Actual

✅ **Completado:**
- Endpoint `/test/simulate-alert` ahora crea órdenes automáticamente cuando `trade_enabled=true`
- Logging mejorado para capturar errores específicos
- Scripts de diagnóstico creados
- Mensajes de error más detallados en Telegram

❌ **Pendiente:**
- Las órdenes SL/TP fallan al crearse después de una orden BUY ejecutada
- Necesitamos identificar el error específico del exchange

## Acción Inmediata Requerida

### 1. Ejecutar Diagnóstico

Cuando vuelvas a crear una orden de prueba y falle SL/TP, ejecuta:

```bash
# En AWS server
docker compose exec backend-aws bash /app/tools/diagnose_sl_tp_failure.sh ORDER_ID SYMBOL
```

Esto mostrará:
- Los payloads exactos enviados al exchange
- Las respuestas del exchange con códigos de error
- Los parámetros usados
- Los errores específicos

### 2. Compartir los Resultados

Comparte:
- El código de error específico (229, 40004, 220, etc.)
- El payload JSON completo que se envió
- La respuesta del exchange

### 3. Ajustar la Lógica

Una vez que tengamos el error específico, ajustaremos:
- El cálculo de `ref_price` si es error 229
- Los campos del payload si es error 40004
- El `side` si es error 220
- El formato del precio si es error 308

## Solución Temporal

Mientras tanto, puedes crear órdenes SL/TP manualmente usando el endpoint de referencia:

```bash
POST /manual-trade/confirm
{
  "symbol": "SOL_USDT",
  "side": "BUY",
  "quantity": 0.059,
  "price": 167.23,
  "sl_percentage": 3.0,
  "tp_percentage": 3.0,
  "sl_tp_mode": "conservative"
}
```

Este endpoint funciona correctamente y puedes usar sus logs como referencia.

## Archivos Clave

- `backend/app/services/exchange_sync.py` - Crea SL/TP automáticamente
- `backend/app/services/tp_sl_order_creator.py` - Lógica reutilizable
- `backend/app/services/brokers/crypto_com_trade.py` - Cliente del exchange con logging HTTP
- `backend/app/api/routes_manual_trade.py` - Flujo de referencia que funciona

