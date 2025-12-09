# Análisis de Logs - Signal Throttle

**Fecha:** 2025-12-09  
**Estado:** Signal Monitor está corriendo, pero las alertas pueden estar siendo bloqueadas

---

## Hallazgos del Análisis de Logs

### ✅ Estado del Servicio

1. **Signal Monitor está CORRIENDO:**
   - El servicio está activo y procesando señales
   - Está en el ciclo #79+ (ha estado corriendo por un tiempo)
   - Está evaluando múltiples símbolos cada 30 segundos

2. **Señales están siendo DETECTADAS:**
   - Se detectan señales BUY para múltiples símbolos:
     - XRP_USDT, ADA_USDT, DOGE_USDT, LTC_USDT, BCH_USDT
     - XLM_USDT, TRX_USDT, BONK_USDT, y muchos más
   - Las decisiones son: `DECISION: SENT (buy_alert_enabled enabled)`

3. **Procesamiento de Alertas:**
   - Se ve el mensaje: `🟢 NEW BUY signal detected for {symbol} - processing alert`
   - Esto indica que el código está llegando a la sección de envío de alertas

### ⚠️ Problema Identificado

**Las alertas NO se están enviando completamente:**

1. **No se ven mensajes de "BUY alert SENT":**
   - Aunque se detectan señales y se decide "SENT"
   - No aparecen mensajes de confirmación de envío
   - No se ven llamadas a `record_signal_event`

2. **Posibles causas:**
   - Las alertas están siendo bloqueadas por el throttle interno (`should_send_alert`)
   - Hay un error silencioso en el envío de Telegram
   - El código no está llegando a la sección de `record_signal_event`

### 🔍 Análisis del Flujo

Según el código en `signal_monitor.py`:

1. **Detección de señal:** ✅ Funcionando
   ```
   🟢 BUY signal detected for {symbol}
   ```

2. **Decisión de alerta:** ✅ Funcionando
   ```
   🔍 {symbol} BUY alert decision: ... → DECISION: SENT
   ```

3. **Procesamiento de alerta:** ✅ Llegando aquí
   ```
   🟢 NEW BUY signal detected for {symbol} - processing alert
   ```

4. **Verificación de throttle interno:** ❓ No se ve en logs
   - Debería haber mensajes de "throttled" o "should_send"
   - No aparecen en los logs recientes

5. **Envío de alerta:** ❌ No se ve confirmación
   - Debería aparecer: `✅ BUY alert SENT for {symbol}`
   - No aparece en los logs

6. **Registro de evento:** ❌ No se ejecuta
   - `record_signal_event()` solo se llama después de envío exitoso
   - Como no hay envío, no hay registro

---

## Diagnóstico Detallado

### Verificar Throttle Interno

El código tiene un throttle interno (`should_send_alert`) que puede estar bloqueando las alertas:

```python
# Línea ~1217 en signal_monitor.py
should_send, buy_reason = self.should_send_alert(
    symbol=symbol,
    side="BUY",
    current_price=current_price,
    ...
)
if not should_send:
    logger.debug(f"⏭️  BUY alert throttled for {symbol}: {buy_reason}")
```

**Problema:** Los mensajes de throttle son `logger.debug()`, que pueden no aparecer en los logs si el nivel de log es INFO o superior.

### Verificar Envío de Telegram

Si `should_send=True`, el código intenta enviar:

```python
# Línea ~1262
result = telegram_notifier.send_buy_signal(...)
if result is False:
    logger.error(f"❌ Failed to send BUY alert...")
else:
    logger.info(f"✅ BUY alert SENT for {symbol}...")
    record_signal_event(...)  # Solo se ejecuta si result != False
```

**Problema:** Si `send_buy_signal()` falla silenciosamente o retorna `None`, no se registra el evento.

---

## Soluciones Recomendadas

### 1. Aumentar Nivel de Logging para Throttle

Cambiar los mensajes de throttle de `debug` a `info` para verlos en los logs:

```python
# En signal_monitor.py línea ~1226
if not should_send:
    logger.info(f"⏭️  BUY alert throttled for {symbol}: {buy_reason}")  # Cambiar de debug a info
```

### 2. Verificar Estado de Telegram

Verificar que Telegram esté funcionando correctamente:

```bash
# En AWS
docker compose logs backend-aws | grep -i telegram | tail -50
```

### 3. Verificar Throttle Interno

El throttle interno usa `last_alert_states` en memoria. Si el servicio se reinició, este estado se perdió, pero las señales pueden estar siendo bloqueadas por:

- **Cooldown:** `ALERT_COOLDOWN_MINUTES` (default: 5 minutos)
- **Cambio de precio mínimo:** `ALERT_MIN_PRICE_CHANGE_PCT` (default: 1.0%)

### 4. Agregar Logging Adicional

Agregar logging antes de `record_signal_event` para ver si se está ejecutando:

```python
# Antes de record_signal_event
logger.info(f"📝 About to record signal event for {symbol} BUY at {current_price}")
try:
    record_signal_event(...)
    logger.info(f"✅ Signal event recorded for {symbol} BUY")
except Exception as e:
    logger.error(f"❌ Failed to record signal event: {e}", exc_info=True)
```

---

## Próximos Pasos

1. ✅ **Verificar logs con nivel DEBUG:**
   ```bash
   # Cambiar nivel de log a DEBUG temporalmente
   # O buscar específicamente mensajes de throttle
   ```

2. ✅ **Verificar estado de Telegram:**
   - Ver si hay errores de conexión
   - Verificar que el bot esté activo

3. ✅ **Revisar throttle interno:**
   - Verificar valores de `last_alert_states`
   - Verificar configuración de cooldown y cambio de precio mínimo

4. ✅ **Agregar logging adicional:**
   - Para rastrear el flujo completo
   - Para identificar dónde se está bloqueando

---

## Conclusión

El signal monitor **está corriendo correctamente** y detectando señales, pero:

- Las alertas pueden estar siendo bloqueadas por el throttle interno
- Los mensajes de throttle son `debug` y no aparecen en los logs
- No se están registrando eventos en la tabla `signal_throttle_state`

**Recomendación inmediata:** Aumentar el nivel de logging para throttle y verificar el estado de Telegram.

---

**Última Actualización:** 2025-12-09
