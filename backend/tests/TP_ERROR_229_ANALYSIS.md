# Análisis del Error 229 (INVALID_REF_PRICE) en TAKE_PROFIT_LIMIT

## Estado Actual

### Problema
Las órdenes de Take Profit (TAKE_PROFIT_LIMIT) fallan con error 229 (INVALID_REF_PRICE) tanto en flujo automático como manual.

### Cambios Implementados

1. **Logging mejorado**: Se implementó logging detallado con `[TP_ORDER][AUTO]` y `[TP_ORDER][MANUAL]` para comparar payloads.

2. **Configuración de logging centralizada**: 
   - `backend/app/core/logging_config.py` con `setup_logging()` y `get_tp_logger()`
   - Logging configurado temprano en `main.py` y en scripts de prueba

3. **Correcciones en payload**:
   - `side` ahora solo usa mayúsculas (`SELL`) para evitar error 40004
   - `ref_price` intenta obtener precio de mercado actual de Crypto.com API
   - Fallback a `entry_price` si no se puede obtener precio de mercado
   - Fallback final a TP price

### Payload Actual
```json
{
  "instrument_name": "AKT_USDT",
  "type": "TAKE_PROFIT_LIMIT",
  "price": "1.5632",
  "quantity": "6.5",
  "trigger_price": "1.5632",
  "ref_price": "1.5177",  // entry_price (fallback)
  "trigger_condition": ">= 1.5632",
  "side": "SELL"
}
```

### Observaciones

1. **Error 229 persiste**: Aunque se intenta obtener precio de mercado actual, el código sigue usando `entry_price` (1.5177) como fallback.

2. **Algunas variaciones devuelven order_id**: Las respuestas incluyen `order_id`, pero luego fallan con error 229, sugiriendo que la API acepta el formato pero rechaza el valor de `ref_price`.

3. **STOP_LIMIT funciona**: Las órdenes STOP_LIMIT usan `entry_price` como `ref_price` y funcionan correctamente, lo que sugiere que TAKE_PROFIT_LIMIT podría tener requisitos diferentes.

### Próximos Pasos Sugeridos

1. **Verificar obtención de precio de mercado**: Confirmar que la llamada a `/public/get-tickers` funciona correctamente y devuelve el precio actual.

2. **Comparar con órdenes exitosas**: Buscar órdenes TAKE_PROFIT_LIMIT exitosas en el historial para comparar el formato de `ref_price`.

3. **Probar sin `ref_price`**: Intentar crear una variación sin `ref_price` para ver si es realmente requerido.

4. **Revisar documentación Crypto.com**: Verificar los requisitos exactos de `ref_price` para TAKE_PROFIT_LIMIT en la documentación oficial.

5. **Probar con precio de mercado actual**: Asegurarse de que `ref_price` sea el precio de mercado actual en el momento de crear la orden, no un precio histórico.

### Scripts de Diagnóstico

- `backend/tests/test_manual_tp.py`: Simula creación manual de TP
- `backend/tests/extract_payloads.py`: Extrae y compara payloads AUTO vs MANUAL
- `backend/tests/analyze_tp_errors.py`: Analiza payloads y identifica problemas potenciales

### Comandos Útiles

```bash
# Ejecutar test manual
docker compose exec backend-aws python3 /app/tests/test_manual_tp.py

# Ver logs de TP
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]" | tail -50

# Extraer payloads
docker compose logs backend-aws 2>&1 | python3 /app/tests/extract_payloads.py -
```

