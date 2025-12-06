# Fix: Simulación Siempre es BUY, Nunca SELL

**Fecha:** 2025-12-01  
**Estado:** ✅ Resuelto

## Problema

El botón de simulación (TEST) en el dashboard estaba simulando tanto alertas BUY como SELL dependiendo de qué alertas estuvieran habilitadas. El usuario requiere que la simulación **siempre sea de compra (BUY)**, nunca de venta (SELL).

## Solución

Modificado `frontend/src/app/page.tsx` para que:
1. **Siempre simule solo BUY** (compra)
2. **Ignore completamente** si SELL está habilitado
3. **Mensaje de confirmación** actualizado para indicar que solo simula BUY

### Cambios Realizados

**Antes:**
```typescript
// Simulaba BUY y/o SELL dependiendo de qué alertas estuvieran habilitadas
if (buyAlertEnabled) {
  const buyResult = await simulateAlert(symbol, 'BUY', true, amountUSD);
  results.push({ type: 'BUY', result: buyResult });
}
if (sellAlertEnabled) {
  const sellResult = await simulateAlert(symbol, 'SELL', true, amountUSD);
  results.push({ type: 'SELL', result: sellResult });
}
```

**Después:**
```typescript
// Siempre simula solo BUY (compra)
console.log(`🧪 Simulando alerta BUY para ${symbol} con amount=${amountUSD}...`);
const buyResult = await simulateAlert(symbol, 'BUY', true, amountUSD);
results.push({ type: 'BUY', result: buyResult });
```

### Archivos Modificados

- `frontend/src/app/page.tsx` (líneas ~8873-8896)
  - Eliminada lógica condicional para SELL
  - Siempre ejecuta solo simulación BUY
  - Actualizado mensaje de confirmación
  - Actualizado tooltip del botón

## Comportamiento Actual

1. Usuario hace clic en botón "🧪 TEST"
2. Se muestra confirmación: "¿Simular alerta BUY para {symbol}?"
3. Si confirma, **solo se simula BUY** (nunca SELL)
4. Se envía alerta de Telegram BUY
5. Si Trade=YES, se crea orden BUY automáticamente

## Notas

- El backend (`/api/test/simulate-alert`) sigue soportando tanto BUY como SELL, pero el frontend ahora solo llama con `signal_type: "BUY"`
- Si en el futuro se necesita simular SELL, se puede agregar un botón separado o un parámetro adicional
- La simulación de BUY es la más común para testing, ya que permite probar el flujo completo de compra → SL/TP






