# Signal Throttle - Hallazgos del Monitoreo

**Fecha:** 2025-12-09  
**Estado:** 🔍 Problema identificado

---

## Hallazgos Principales

### ✅ Lo que está funcionando:

1. **Signal Monitor está corriendo:** El servicio está activo y procesando señales cada 30 segundos
2. **Señales detectadas:** Se detectan señales BUY para múltiples símbolos correctamente
3. **Decisiones correctas:** Las decisiones son "SENT" cuando `buy_alert_enabled=True`
4. **Logging mejorado:** Los nuevos mensajes de logging están funcionando

### ❌ Problema identificado:

**Las alertas están siendo bloqueadas por un lock de procesamiento simultáneo**

#### Síntomas:

```
⏭️  BUY alert throttled for {symbol}: Another thread is already processing {symbol} BUY alert (lock age: X.XXs, remaining: XXX.XXs)
```

#### Causa:

1. **Múltiples threads procesando la misma alerta:**
   - El signal monitor corre cada 30 segundos
   - Múltiples ciclos detectan la misma señal BUY
   - Cada ciclo intenta procesar la alerta simultáneamente

2. **Lock de 300 segundos (5 minutos):**
   - Cuando un thread adquiere el lock, otros threads esperan
   - El lock tiene un timeout de 300 segundos
   - Si el primer thread no completa el proceso, los demás quedan bloqueados

3. **El primer thread no completa el envío:**
   - No se ven mensajes de "BUY alert SENT" después de "Lock acquired"
   - No se ven mensajes de "Recording signal event"
   - Esto sugiere que el thread que adquiere el lock no está completando el proceso

---

## Análisis del Flujo

### Flujo esperado:

1. ✅ Señal BUY detectada
2. ✅ Decisión: "SENT"
3. ✅ "processing alert"
4. ✅ Lock adquirido
5. ❌ **AQUÍ SE DETIENE** - No se ve "BUY alert SENT"
6. ❌ No se ejecuta `record_signal_event()`
7. ❌ No aparecen eventos en el dashboard

### Flujo actual observado:

1. ✅ Señal BUY detectada
2. ✅ Decisión: "SENT"
3. ✅ "processing alert"
4. ✅ Lock adquirido (primer thread)
5. ⚠️ Otros threads detectan el lock y se bloquean
6. ❌ El primer thread no completa el proceso (no se ve "BUY alert SENT")
7. ❌ Los otros threads quedan bloqueados esperando

---

## Posibles Causas

### 1. Error silencioso en el envío de Telegram

El código intenta enviar la alerta pero falla silenciosamente:

```python
result = telegram_notifier.send_buy_signal(...)
if result is False:
    logger.error(...)  # Esto debería aparecer en logs
else:
    logger.info("✅ BUY alert SENT...")  # Esto NO aparece
```

**Verificación necesaria:** Revisar si hay errores de Telegram en los logs.

### 2. El proceso está tomando mucho tiempo

El envío de Telegram puede estar tomando más de 300 segundos, causando que:
- El lock expire
- Otros threads intenten procesar
- Se cree un ciclo de bloqueos

**Verificación necesaria:** Revisar tiempos de respuesta de Telegram.

### 3. Excepción no capturada

Puede haber una excepción entre "Lock acquired" y "BUY alert SENT" que no se está registrando.

**Verificación necesaria:** Revisar logs completos para excepciones.

### 4. Condición que bloquea el envío

Puede haber una condición (como `should_send=False`) que bloquea el envío después de adquirir el lock.

**Verificación necesaria:** Revisar el código entre "Lock acquired" y "send_buy_signal".

---

## Próximos Pasos de Diagnóstico

### 1. Buscar errores de Telegram

```bash
bash scripts/aws_backend_logs.sh --tail 10000 | grep -E "(telegram|Failed to send|send_buy_signal)" | tail -50
```

### 2. Buscar excepciones

```bash
bash scripts/aws_backend_logs.sh --tail 10000 | grep -E "(Exception|Error|Traceback)" | tail -50
```

### 3. Verificar tiempos de procesamiento

```bash
bash scripts/aws_backend_logs.sh --tail 10000 | grep -E "(processing alert|Lock acquired|alert SENT)" | tail -100
```

### 4. Revisar código entre lock y envío

Revisar el código en `signal_monitor.py` entre:
- Línea ~1081: "Lock acquired"
- Línea ~1262: "send_buy_signal"

Para identificar qué puede estar bloqueando el proceso.

---

## Recomendaciones

### Inmediatas:

1. **Agregar más logging:**
   - Después de adquirir el lock
   - Antes de cada verificación importante
   - Después de cada paso crítico

2. **Reducir timeout del lock:**
   - 300 segundos es muy largo
   - Reducir a 60 segundos debería ser suficiente

3. **Verificar estado de Telegram:**
   - Asegurarse de que Telegram está funcionando
   - Verificar que no hay errores de conexión

### A mediano plazo:

1. **Mejorar manejo de locks:**
   - Usar un sistema de cola en lugar de locks
   - O mejorar el sistema de locks para evitar bloqueos

2. **Agregar métricas:**
   - Tiempo promedio de procesamiento de alertas
   - Tasa de éxito/fallo de envío
   - Número de alertas bloqueadas por lock

---

## Conclusión

El problema principal es que **las alertas están siendo bloqueadas por un lock de procesamiento simultáneo**, y el thread que adquiere el lock no está completando el proceso de envío.

**Necesitamos:**
1. Identificar por qué el primer thread no completa el proceso
2. Reducir el timeout del lock
3. Agregar más logging para rastrear el problema

---

**Última Actualización:** 2025-12-09 10:05 WITA
