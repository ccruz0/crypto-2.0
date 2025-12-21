# 🔍 Diagnóstico: ¿Por qué no se envió una alerta?

## 📋 Checklist de Verificación

Cuando una alerta no se envía aunque se detecta una señal BUY/SELL, verifica estas condiciones en orden:

### 1. ✅ Flags de Alerta Habilitados
- **`alert_enabled = True`** (master switch - debe estar activado)
- **`buy_alert_enabled = True`** (para alertas BUY)
- **`sell_alert_enabled = True`** (para alertas SELL)

**Cómo verificar:**
- En el dashboard, revisa la columna "Actions" → botón "ALERTS ▼"
- O revisa los logs: busca `🔍 {symbol} BUY alert decision`

**Si está deshabilitado:**
- El log mostrará: `DECISION: SKIPPED (alert_enabled=False)` o `DECISION: SKIPPED (buy_alert_enabled=False)`

---

### 2. ⏱️ Throttling (Cooldown + Cambio de Precio)

El sistema requiere **AMBAS** condiciones para enviar alertas del mismo lado:

#### A) Cooldown (Tiempo de espera)
- **Por defecto:** 5 minutos desde la última alerta BUY/SELL
- **Configurable:** Campo `alert_cooldown_minutes` en watchlist

#### B) Cambio de Precio Mínimo
- **Por defecto:** 1.0% de cambio absoluto desde la última alerta
- **Configurable:** Campo `min_price_change_pct` en watchlist

**Cómo verificar:**
- Busca en logs: `⏭️ BUY alert throttled for {symbol}: {reason}`
- El mensaje indicará cuál condición no se cumplió:
  - `Throttled: cooldown X min < Y min` → No ha pasado suficiente tiempo
  - `Throttled: price change X% < Y%` → El precio no ha cambiado lo suficiente

**Ejemplo de log bloqueado:**
```
⏭️ BUY alert throttled for BTC_USDT: Throttled: cooldown 2.3 min < 5 min (remaining 2.7 min). Requires BOTH cooldown >= 5 min AND price change >= 1.00%
```

---

### 3. 🔒 Locks de Procesamiento

El sistema usa locks para evitar alertas duplicadas cuando múltiples ciclos corren simultáneamente.

**Cómo verificar:**
- Busca en logs: `🔒 Alert sending already in progress for {symbol}`
- Si aparece, significa que otro ciclo está procesando la misma alerta

**Solución:** Espera unos segundos (el lock expira automáticamente)

---

### 4. 📊 Señal No Detectada

Aunque el dashboard muestre "BUY", el backend puede no detectar la señal si:
- Los indicadores técnicos no cumplen todos los criterios
- Falta algún indicador requerido (RSI, MA, EMA, etc.)

**Cómo verificar:**
- Busca en logs: `SignalMonitor: BUY signal candidate for {symbol}`
- Si no aparece o aparece como `should_buy=False`, la señal no se detectó

---

### 5. 🚫 Verificación Temprana de `alert_enabled`

Si `alert_enabled=False`, el sistema sale temprano y no procesa ninguna señal.

**Cómo verificar:**
- Busca en logs: `🚫 BLOQUEADO: {symbol} - Las alertas están deshabilitadas`
- Si aparece, el sistema no procesará ninguna señal para ese símbolo

---

## 🔍 Cómo Diagnosticar una Alerta Específica

### Paso 1: Revisar los Logs del Símbolo

Busca en los logs del backend por el símbolo específico:

```bash
# Ejemplo para BTC_USDT
grep "BTC_USDT" /path/to/logs | grep -E "alert|BUY|throttle|BLOCKED|SKIPPED"
```

### Paso 2: Verificar Flags en Base de Datos

```sql
SELECT symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled, 
       alert_cooldown_minutes, min_price_change_pct
FROM watchlist_items 
WHERE symbol = 'BTC_USDT';
```

### Paso 3: Verificar Estado de Throttling

El sistema registra eventos de throttling en la tabla `signal_throttle_states`:

```sql
SELECT * FROM signal_throttle_states 
WHERE symbol = 'BTC_USDT' AND side = 'BUY' 
ORDER BY last_time DESC 
LIMIT 5;
```

Revisa el campo `emit_reason` para ver por qué se bloqueó:
- `BLOCKED: Throttled: cooldown...` → Cooldown no cumplido
- `BLOCKED: Throttled: price change...` → Cambio de precio insuficiente
- `Blocked: alert_enabled=False` → Flag deshabilitado
- `Blocked: buy_alert_enabled=False` → Flag específico deshabilitado

---

## 🛠️ Soluciones Comunes

### Problema: Throttling bloquea alertas
**Solución:** 
- Reduce `alert_cooldown_minutes` (ej: de 5 a 1 minuto)
- Reduce `min_price_change_pct` (ej: de 1.0% a 0.5%)
- O espera a que se cumplan las condiciones

### Problema: Flags deshabilitados
**Solución:**
- Activa `alert_enabled` en el dashboard
- Activa `buy_alert_enabled` o `sell_alert_enabled` según corresponda

### Problema: Señal no detectada
**Solución:**
- Verifica que todos los indicadores técnicos estén disponibles
- Revisa la configuración de la estrategia (RSI thresholds, MA checks, etc.)

---

## 📝 Logs Clave a Buscar

| Log | Significado |
|-----|-------------|
| `🔍 {symbol} BUY alert decision: ... DECISION: SENT` | ✅ Alerta debería enviarse |
| `🔍 {symbol} BUY alert decision: ... DECISION: SKIPPED` | ❌ Alerta bloqueada por flags |
| `⏭️ BUY alert throttled for {symbol}` | ⏱️ Alerta bloqueada por throttling |
| `🟢 NEW BUY signal detected for {symbol}` | ✅ Señal detectada, procesando |
| `✅ BUY alert SENT for {symbol}` | ✅ Alerta enviada exitosamente |
| `🚫 BLOQUEADO: {symbol}` | ❌ Alerta bloqueada por configuración |

---

## 🎯 Resumen

**Las alertas se envían SOLO cuando se cumplen TODAS estas condiciones:**

1. ✅ `alert_enabled = True` (master switch)
2. ✅ `buy_alert_enabled = True` o `sell_alert_enabled = True` (según el lado)
3. ✅ Señal BUY/SELL detectada correctamente
4. ✅ Cooldown cumplido (tiempo desde última alerta)
5. ✅ Cambio de precio suficiente (desde última alerta)
6. ✅ No hay lock activo (otro ciclo procesando)

**Si alguna condición falla, la alerta NO se enviará y aparecerá en los logs con la razón específica.**





