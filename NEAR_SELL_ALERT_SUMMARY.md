# Resumen: NEAR muestra botón SELL pero no envía alertas

## 🔍 Problema Reportado

NEAR_USDT muestra el botón rojo (SELL) en el dashboard pero no se envían alertas de venta a Telegram o Throttle.

## ✅ Problemas Identificados y Resueltos

### 1. Columnas Faltantes en Base de Datos (CRÍTICO - RESUELTO)

**Problema:** El modelo `SignalThrottleState` esperaba columnas que no existían en la tabla:
- ❌ `previous_price` - NO existía
- ❌ `emit_reason` - NO existía  
- ❌ `force_next_signal` - NO existía

**Solución:** Se agregaron las tres columnas:
```sql
ALTER TABLE signal_throttle_states ADD COLUMN previous_price FLOAT NULL;
ALTER TABLE signal_throttle_states ADD COLUMN emit_reason VARCHAR(500);
ALTER TABLE signal_throttle_states ADD COLUMN force_next_signal BOOLEAN DEFAULT FALSE;
```

**Impacto:** Sin estas columnas, las consultas de throttle state fallaban, impidiendo verificar si se debía enviar una alerta.

### 2. Configuración de NEAR_USDT (CORRECTO)

- ✅ **Existe en watchlist**: ID 21
- ✅ **Flags habilitados**: 
  - `alert_enabled=True`
  - `sell_alert_enabled=True`
  - `buy_alert_enabled=True`
- ✅ **Datos de mercado disponibles**: Precio, RSI, MA50, EMA10

### 3. Condiciones SELL (VERIFICADO)

- ✅ **RSI > 70**: RSI=74.26 (cumple condición)
- ✅ **Throttle debería permitir**:
  - Cambio de precio: 8.32% (mínimo 1.0%) ✅
  - Cooldown: 12,571 minutos (mínimo 1.0 min) ✅

## 📊 Estado Actual

### Logs Encontrados (Últimos)

```
2025-12-22 06:31:37 - 🔴 SELL signal detected for NEAR_USDT
2025-12-22 06:31:37 - SignalMonitor: SELL signal candidate for NEAR_USDT
2025-12-22 06:31:37 - Failed to load throttle state (previous_price no existe) ❌
2025-12-22 06:31:37 - Failed to record SELL signal event (previous_price no existe) ❌
```

**Después de agregar columnas:**
- ✅ Ya no hay errores de `previous_price does not exist`
- ⏳ Esperando próximo ciclo para verificar procesamiento completo

## 🔄 Flujo Esperado Ahora

1. ✅ Se detecta señal SELL: `🔴 SELL signal detected for NEAR_USDT`
2. ✅ Se carga throttle state (ya no falla por columnas faltantes)
3. ✅ Se verifica `should_emit_signal()` (throttle debería permitir)
4. ✅ Se procesa alerta SELL si condiciones se cumplen
5. ✅ Se envía a Telegram/Throttle

## 🎯 Próximos Pasos

### Verificación Inmediata

```bash
# Verificar que no hay más errores
docker logs automated-trading-platform-backend-aws-1 | grep -i "NEAR.*previous_price\|NEAR.*emit_reason"

# Verificar procesamiento de alertas SELL
docker logs automated-trading-platform-backend-aws-1 | grep -i "NEAR.*SELL alert decision\|NEAR.*NEW SELL"

# Verificar si se detecta la señal
docker logs automated-trading-platform-backend-aws-1 | grep -i "NEAR.*SELL signal detected"
```

### Si la Señal SELL Ya No Se Detecta

Si las condiciones cambiaron y el dashboard muestra SELL pero el backend no lo detecta, verificar:
1. **RSI**: Debe ser > 70 para SELL
2. **MA50 < EMA10**: Debe cumplirse con diferencia ≥ 0.5%
3. **Volume**: Debe ser ≥ 0.5x promedio

El dashboard puede mostrar SELL calculado localmente, pero el backend tiene lógica adicional que puede diferir.

## 📝 Archivos Creados

- ✅ `NEAR_SELL_ALERT_FIX.md` - Documentación del problema y solución
- ✅ `diagnose_near_sell_alert.py` - Script de diagnóstico
- ✅ Columnas agregadas a base de datos

## ✅ Conclusión

**Problemas de esquema resueltos:** Las columnas faltantes han sido agregadas. El sistema debería poder procesar alertas SELL correctamente ahora.

**Siguiente ciclo:** El próximo ciclo del SignalMonitorService (cada 30 segundos) debería procesar NEAR_USDT sin errores de base de datos.

**Si aún no funciona:** Verificar que las condiciones SELL se sigan cumpliendo según la lógica del backend (no solo del dashboard).

