# Diagnóstico: DOT cumple parámetros BUY pero no envía señales

## Problema
DOT_USDT cumple los parámetros para una alerta de BUY pero no se envían señales a Throttle o a Telegram.

## Posibles Causas Identificadas (Ordenadas por Probabilidad)

### 1. 🔴 **Bot Detenido (CAUSA MÁS PROBABLE - CRÍTICO)**
**Causa más probable según la imagen del dashboard**

El dashboard muestra **"Bot Detenido"** en rojo. Si el servicio `SignalMonitorService` no está corriendo (`is_running = False`), **NO procesará señales ni enviará alertas**.

**Verificación:**
- Revisar logs del backend para confirmar si `SignalMonitorService` está corriendo
- Verificar estado del servicio con endpoint `/api/services/status`
- Buscar en logs: `SignalMonitorService loop iteration` o `SignalMonitorService cycle`

**Ubicación del código:**
- `backend/app/services/signal_monitor.py` línea 3646: `while self.is_running:`
- Si `is_running = False`, el loop no ejecuta `monitor_signals()`

**Solución:**
- Iniciar el servicio con `/api/services/start` o verificar que se inicia automáticamente en `main.py`

---

### 3. ⚠️ **Flags de Alerta Deshabilitados**

El código requiere **AMBOS** flags habilitados para enviar alertas BUY:

1. **`alert_enabled`** = `True` (master switch)
2. **`buy_alert_enabled`** = `True` (flag específico para alertas BUY)

**Verificación en código:**
```python
# backend/app/services/signal_monitor.py línea 1303
if buy_signal and watchlist_item.alert_enabled and buy_alert_enabled:
    # Solo aquí se procesa la alerta
```

**Cómo verificar:**
- Consultar base de datos para DOT_USDT:
  ```sql
  SELECT symbol, alert_enabled, buy_alert_enabled, trade_enabled 
  FROM watchlist_items 
  WHERE symbol = 'DOT_USDT';
  ```
- O desde el dashboard, verificar que ambos están activados

**Logs a buscar:**
- `🔍 DOT_USDT BUY alert decision: buy_signal=True, alert_enabled=..., buy_alert_enabled=... → DECISION: SKIPPED`
- `🚫 BLOQUEADO: DOT_USDT - Las alertas de compra (BUY) están deshabilitadas`

---

### 2. ⏱️ **Throttling (Cooldown o Cambio de Precio) - SEGUNDA CAUSA MÁS PROBABLE**

**⚠️ CRÍTICO:** El throttle se verifica **ANTES** de procesar alertas y puede cambiar `buy_signal = False`, impidiendo que se envíe la alerta aunque el dashboard muestre BUY.

**Flujo del código:**
1. Se calcula `buy_signal = True` desde `calculate_trading_signals()` (línea 1009)
2. Si `buy_signal = True`, se llama a `should_emit_signal()` para verificar throttling (línea 1081)
3. **Si `should_emit_signal()` retorna `False`** (throttling bloquea):
   - Se registra mensaje de bloqueo (línea 1124): `🚫 BLOQUEADO: {symbol} BUY - {reason}`
   - **Se cambia `buy_signal = False`** (línea 1157) ⚠️
   - Se cambia estado a "WAIT" (línea 1159)
4. Como `buy_signal = False`, **nunca llega a la sección de alertas** (línea 1303)

**Esto explica por qué:**
- El dashboard muestra BUY (calcula señales localmente sin throttle)
- Pero las alertas NO se envían (el backend bloquea antes de procesar)

**Ubicación del código:**
- `backend/app/services/signal_monitor.py` línea 1081: `should_emit_signal()` - verificación de throttle
- `backend/app/services/signal_monitor.py` línea 1157: `buy_signal = False` - cuando throttle bloquea
- `backend/app/services/signal_monitor.py` línea 1303: `if buy_signal and alert_enabled and buy_alert_enabled:` - nunca se ejecuta si throttle bloqueó
- `backend/app/services/signal_throttle.py`: `should_emit_signal()` - lógica de throttle

**Verificación:**
- Buscar en logs: `🚫 BLOQUEADO: DOT_USDT BUY - {razón}`
- Buscar: `SignalMonitor: BUY signal candidate for DOT_USDT` seguido de bloqueo
- Revisar tabla `signal_throttle_states` para ver última señal enviada y comparar tiempo/precio
- Verificar `min_price_change_pct` y `alert_cooldown_minutes` en la configuración de DOT_USDT

**Logs relevantes a buscar:**
- `🔍 DOT_USDT signal check: buy_signal=True` (indica que se detectó señal)
- `SignalMonitor: BUY signal candidate for DOT_USDT` (antes del throttle check)
- `🚫 BLOQUEADO: DOT_USDT BUY - {razón}` (throttle bloqueó)
- NO debería aparecer: `🔍 DOT_USDT BUY alert decision` (porque buy_signal ya es False)

**Razones comunes de bloqueo por throttle:**
- `Price change {X}% < minimum {Y}% required` - cambio de precio insuficiente
- `Cooldown not met: {X} minutes elapsed < {Y} minutes required` - no ha pasado suficiente tiempo

---

### 4. 🔍 **Condiciones BUY No Cumplidas Realmente** (Menos probable si el dashboard muestra BUY)

Aunque el dashboard muestre señal BUY, el código del backend puede evaluar diferentes condiciones.

**Verificación:**
- Buscar logs: `should_trigger_buy_signal` para DOT_USDT
- Revisar si RSI, MA50, EMA10 cumplen los umbrales configurados
- Verificar que no hay indicadores faltantes (`Missing indicators`)

**Logs a buscar:**
- `⚠️ DOT_USDT: Missing indicators for ... BUY check: ...`
- Razones de rechazo en `BuyDecision.reasons`

---

### 5. 🚫 **Signal Throttle Bloqueando** (Ya cubierto en punto 2 - throttling)

El sistema tiene un mecanismo de throttle que verifica en la base de datos si debe emitir señal.

**Ubicación:**
- `backend/app/services/signal_throttle.py`: `should_emit_signal()`
- Se consulta tabla `signal_throttle_states` para ver última señal

**Verificación:**
- Revisar tabla `signal_throttle_states` para DOT_USDT
- Buscar logs: `should_emit_signal` para DOT_USDT con resultado `False`

---

### 6. 🔒 **Lock de Alerta Activo**

El sistema usa locks para prevenir alertas duplicadas. Si hay un lock activo, la alerta se bloquea.

**Ubicación:**
- `backend/app/services/signal_monitor.py` línea 1309: `lock_key = f"{symbol}_BUY"`
- Línea 350-358: verificación de lock

**Verificación:**
- Buscar en logs: `Another thread is already processing DOT_USDT BUY alert`
- Los locks expiran después de 300 segundos (5 minutos)

---

## Plan de Diagnóstico Recomendado

### Paso 1: Verificar Estado del Servicio
```bash
# Verificar logs del servicio
docker logs backend-aws | grep -i "SignalMonitorService" | tail -50

# Verificar estado via API (si disponible)
curl http://localhost:8000/api/services/status
```

### Paso 2: Verificar Flags en Base de Datos
```sql
SELECT 
    symbol, 
    alert_enabled, 
    buy_alert_enabled, 
    sell_alert_enabled,
    trade_enabled,
    trade_on_margin
FROM watchlist_items 
WHERE symbol = 'DOT_USDT';
```

### Paso 3: Buscar Logs Específicos de DOT_USDT
```bash
# 1. Buscar si se detectó la señal BUY
docker logs backend-aws | grep "DOT_USDT.*BUY signal detected"

# 2. Buscar candidato de señal (antes del throttle)
docker logs backend-aws | grep "DOT_USDT.*signal candidate"

# 3. Buscar bloqueos por throttle (CRÍTICO)
docker logs backend-aws | grep "DOT_USDT.*BLOQUEADO\|BLOCKED"

# 4. Buscar decisiones de alerta (solo aparecerá si pasó el throttle)
docker logs backend-aws | grep "DOT_USDT.*BUY alert decision"

# 5. Buscar si se procesó la alerta
docker logs backend-aws | grep "DOT_USDT.*NEW BUY signal detected"

# 6. Buscar verificación de throttle específica
docker logs backend-aws | grep "DOT_USDT.*throttle check"
```

### Paso 4: Verificar Signal Throttle States
```sql
SELECT 
    symbol,
    side,
    strategy_key,
    last_price,
    last_time,
    force_next_signal
FROM signal_throttle_states
WHERE symbol = 'DOT_USDT'
ORDER BY last_time DESC;
```

### Paso 5: Verificar Condiciones BUY
```bash
# Buscar evaluación de condiciones
docker logs backend-aws | grep "DOT_USDT.*should_trigger_buy_signal"

# Buscar indicadores faltantes
docker logs backend-aws | grep "DOT_USDT.*Missing indicators"
```

---

## Soluciones Rápidas

### Si el Bot Está Detenido:
1. Iniciar servicios: `POST /api/services/start`
2. Verificar que se inició: `GET /api/services/status`
3. Confirmar en logs que el loop está corriendo

### Si Flags Están Deshabilitados:
1. Habilitar `alert_enabled = True` desde el dashboard
2. Habilitar `buy_alert_enabled = True` desde el dashboard
3. Verificar que ambos se guardaron correctamente

### Si Hay Throttling:
1. Verificar última señal enviada en `signal_throttle_states`
2. Esperar que pase el cooldown o cambiar el precio suficiente
3. O usar `force_next_signal = True` para forzar próxima señal (si está disponible)

---

## Código Clave para Revisar

1. **Verificación de flags**: `backend/app/services/signal_monitor.py` línea 1303
2. **Throttling check**: `backend/app/services/signal_monitor.py` línea 1471
3. **Signal throttle**: `backend/app/services/signal_throttle.py` línea 74
4. **Loop principal**: `backend/app/services/signal_monitor.py` línea 3646
5. **Condiciones BUY**: `backend/app/services/trading_signals.py` línea 44

---

## Notas Importantes

- **El estado "Bot Detenido" en el dashboard es un indicador crítico** - si el servicio no está corriendo, ninguna alerta se procesará
- **El dashboard muestra señales calculadas localmente** - puede mostrar BUY aunque el backend esté bloqueando por throttle
- **Throttling bloquea ANTES de procesar alertas** - si `should_emit_signal()` retorna False, `buy_signal` se cambia a False y nunca se procesa la alerta (línea 1157)
- **DRY RUN no debería afectar alertas** - las alertas se envían independientemente del modo LIVE/DRY RUN
- **Las alertas y órdenes son independientes** - las alertas se envían aunque `trade_enabled = False`
- **Throttling es normal** - previene spam de alertas cuando el precio no cambia significativamente

## Flujo de Decisión Resumido

```
1. calculate_trading_signals() → buy_signal = True/False
   ↓ (si buy_signal = True)
2. should_emit_signal() → buy_allowed = True/False
   ↓ (si buy_allowed = False)
3. buy_signal = False ⚠️ (línea 1157)
   ↓ (nunca llega aquí si buy_signal = False)
4. if buy_signal and alert_enabled and buy_alert_enabled: (línea 1303)
   ↓ (solo si todo es True)
5. Enviar alerta a Telegram/Throttle
```

**El problema:** Si el paso 2 bloquea, el paso 4 nunca se ejecuta.

