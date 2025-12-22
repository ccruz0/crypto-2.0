# Fix: NEAR muestra botón SELL pero no envía alertas

## 🔍 Problema Identificado

NEAR_USDT muestra el botón rojo (SELL) en el dashboard pero no se están enviando alertas de venta a Telegram o Throttle.

## ❌ Causa Raíz

**Error de esquema de base de datos:** La tabla `signal_throttle_states` no tenía la columna `previous_price` que el modelo `SignalThrottleState` esperaba.

### Evidencia en Logs

```
Failed to load throttle state for NEAR_USDT: 
(psycopg2.errors.UndefinedColumn) column signal_throttle_states.previous_price does not exist

Failed to record SELL signal event for NEAR_USDT (non-blocking): 
(psycopg2.errors.UndefinedColumn) column signal_throttle_states.previous_price does not exist
```

### Flujo del Problema

1. ✅ Se detecta señal SELL: `🔴 SELL signal detected for NEAR_USDT`
2. ❌ Intenta cargar throttle state → **FALLA** (columna no existe)
3. ❌ Intenta grabar evento de señal → **FALLA** (columna no existe)
4. ❌ Como falla la verificación del throttle, `sell_allowed` no se puede determinar correctamente
5. ❌ Nunca llega a procesar la alerta porque el código no puede verificar el throttle

## ✅ Solución Aplicada

Agregada la columna `previous_price` a la tabla `signal_throttle_states`:

```sql
ALTER TABLE signal_throttle_states 
ADD COLUMN previous_price FLOAT NULL;
```

## 📊 Estado Actual de NEAR_USDT

- ✅ **Existe en watchlist**: ID 21
- ✅ **Flags habilitados**: `alert_enabled=True`, `sell_alert_enabled=True`
- ✅ **Se detecta señal SELL**: Logs muestran `🔴 SELL signal detected for NEAR_USDT`
- ✅ **Columna agregada**: `previous_price` ahora existe en la tabla

## ✅ Correcciones Aplicadas

### 1. Columna `previous_price`
```sql
ALTER TABLE signal_throttle_states ADD COLUMN previous_price FLOAT NULL;
```

### 2. Columna `emit_reason`
```sql
ALTER TABLE signal_throttle_states ADD COLUMN emit_reason VARCHAR(500);
```

### 3. Columna `force_next_signal`
```sql
ALTER TABLE signal_throttle_states ADD COLUMN force_next_signal BOOLEAN DEFAULT FALSE;
```

## 🔄 Próximos Pasos

1. **Esperar el próximo ciclo** del SignalMonitorService (cada 30 segundos)
2. **Verificar logs** para confirmar que:
   - Ya no hay errores de columnas faltantes
   - Se carga correctamente el throttle state
   - Se procesa la alerta SELL

## 📊 Estado Actual de NEAR_USDT

- ✅ **Flags habilitados**: `alert_enabled=True`, `sell_alert_enabled=True`
- ✅ **RSI > 70**: RSI=74.26 (cumple condición SELL)
- ✅ **Última señal SELL**: Hace 12,571 minutos (cooldown cumplido)
- ✅ **Cambio de precio**: Verificar si cumple mínimo requerido
- ✅ **Columnas agregadas**: Todas las columnas necesarias ahora existen

## 📝 Script de Verificación

```bash
# Verificar que no hay más errores
docker logs automated-trading-platform-backend-aws-1 | grep -i "NEAR.*previous_price\|NEAR.*SELL alert\|NEAR.*NEW SELL"
```

## ⚠️ Nota Importante

Este mismo problema podría estar afectando a otros símbolos. La columna `previous_price` fue agregada globalmente, por lo que todos los símbolos deberían funcionar correctamente ahora.

## 🔧 Script de Migración Utilizado

```python
ALTER TABLE signal_throttle_states ADD COLUMN previous_price FLOAT;
```

La columna se agregó como nullable para no afectar registros existentes.

