# Análisis del Error 220 (INVALID_SIDE) en TAKE_PROFIT_LIMIT

## Estado Actual

### Progreso Logrado ✅
1. **Error 229 resuelto**: `ref_price` ahora se calcula correctamente basado en el precio de mercado:
   - Para SELL: `ref_price = ticker_price * 0.995` (menor que precio de mercado)
   - Para BUY: `ref_price = ticker_price * 1.005` (mayor que precio de mercado)
   - Logs muestran: `Final ref_price=0.640282, ticker=0.6435, tp_price=1.5632, side=SELL`

2. **Payload correcto**: Las órdenes ahora tienen `ref_price='0.6403'` que es menor que el precio de mercado `0.6435`

3. **Validación inicial pasa**: Las órdenes devuelven `order_id`, indicando que pasan la validación inicial de formato

### Problema Actual ❌
**Error 220 (INVALID_SIDE)**: Después de pasar la validación inicial, todas las variaciones fallan con error 220.

### Observaciones
- El `side='SELL'` está en mayúsculas (correcto según análisis anterior)
- El `ref_price` está correctamente calculado (menor que mercado para SELL)
- Las órdenes devuelven `order_id` pero luego fallan con error 220
- El error aparece después de probar todas las variaciones de precio/trigger

### Posibles Causas
1. **`side` no debería estar presente**: Crypto.com podría inferir el `side` automáticamente para TAKE_PROFIT_LIMIT
2. **`ref_price` demasiado lejos de `trigger_price`**: La diferencia entre `ref_price=0.6403` y `trigger_price=1.563` podría ser demasiado grande
3. **Validación interna de Crypto.com**: Podría haber una validación adicional que rechaza órdenes con ciertas combinaciones de parámetros

### Próximos Pasos Sugeridos
1. Probar variaciones sin el campo `side` (dejar que Crypto.com lo infiera)
2. Ajustar `ref_price` para que esté más cerca de `trigger_price` (pero aún menor que mercado para SELL)
3. Revisar documentación oficial de Crypto.com sobre TAKE_PROFIT_LIMIT y el campo `side`

