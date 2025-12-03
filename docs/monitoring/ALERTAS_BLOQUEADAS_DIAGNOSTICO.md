# Diagnóstico: Alertas No Enviadas a Telegram

## Situación Actual

### Puntos de Bloqueo Identificados

El sistema tiene **3 puntos principales** donde las alertas pueden ser bloqueadas antes de llegar a Telegram:

#### 1. **Gatekeeper de Origen** (`telegram_notifier.py`)

**Ubicación:** `backend/app/services/telegram_notifier.py` - función `send_message()`

**Condiciones que bloquean:**
- `origin != "AWS"` y `origin != "TEST"` → **BLOQUEADO**
  - Log: `[TG_LOCAL_DEBUG] Skipping Telegram send for non-AWS/non-TEST origin`
  - Registra en Monitoring con `blocked=True`

**Condiciones que permiten:**
- `origin == "AWS"` → ✅ Permite enviar (prefijo `[AWS]`)
- `origin == "TEST"` → ✅ Permite enviar (prefijo `[TEST]`)

#### 2. **Configuración RUN_TELEGRAM** (`telegram_notifier.py`)

**Ubicación:** `backend/app/services/telegram_notifier.py` - `__init__()`

**Condiciones que bloquean:**
- `RUN_TELEGRAM != "true"` → **BLOQUEADO**
  - Log: `Telegram disabled via RUN_TELEGRAM flag`
  - Log: `[E2E_TEST_CONFIG] Telegram sending disabled by configuration`

**Condiciones que permiten:**
- `RUN_TELEGRAM == "true"` → ✅ Permite enviar

#### 3. **Variables de Entorno Faltantes** (`telegram_notifier.py`)

**Ubicación:** `backend/app/services/telegram_notifier.py` - `__init__()`

**Condiciones que bloquean:**
- `TELEGRAM_BOT_TOKEN` no está configurado → **BLOQUEADO**
- `TELEGRAM_CHAT_ID` no está configurado → **BLOQUEADO**
  - Log: `Telegram disabled: missing env vars`

**Condiciones que permiten:**
- Ambos `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` presentes → ✅ Permite enviar

---

## Flujo Completo de Alertas

```
1. Strategy Layer
   └─> Genera señal BUY/SELL
       └─> Log: [DEBUG_STRATEGY_FINAL]

2. Signal Monitor Layer
   └─> Evalúa cooldowns, exposición, volumen
       └─> Log: SignalMonitor: evaluating
       └─> Si pasa todas las validaciones:
           └─> Llama a emit_alert()
               └─> Log: [ALERT_DECISION]

3. Alert Emitter (emit_alert)
   └─> Verifica dry_run
       └─> Si dry_run=True:
           └─> Log: [ALERT_SKIP] → ❌ NO ENVÍA
       └─> Si dry_run=False:
           └─> Llama a telegram_notifier.send_buy_signal() o send_sell_signal()
               └─> Log: [ALERT_ENQUEUED]

4. Telegram Notifier (send_message)
   └─> Verifica origin (gatekeeper)
       └─> Si origin != "AWS" y != "TEST":
           └─> Log: [TG_LOCAL_DEBUG] → ❌ NO ENVÍA
       └─> Si origin == "AWS" o "TEST":
           └─> Verifica self.enabled (RUN_TELEGRAM)
               └─> Si enabled=False:
                   └─> Log: [E2E_TEST_CONFIG] → ❌ NO ENVÍA
               └─> Si enabled=True:
                   └─> Verifica bot_token y chat_id
                       └─> Si faltan:
                           └─> Log: Telegram disabled: missing env vars → ❌ NO ENVÍA
                       └─> Si están presentes:
                           └─> Intenta enviar a Telegram API
                               └─> Log: [TELEGRAM_SEND]
                               └─> Si éxito:
                                   └─> Log: Telegram message sent successfully
                               └─> Si error:
                                   └─> Log: [TELEGRAM_ERROR]
```

---

## Cómo Diagnosticar Alertas Bloqueadas

### Paso 1: Verificar Configuración en AWS

```bash
cd /Users/carloscruz/automated-trading-platform
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose exec backend-aws env | grep -E "(RUN_TELEGRAM|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID|APP_ENV)"'
```

**Valores esperados:**
- `RUN_TELEGRAM=true`
- `TELEGRAM_BOT_TOKEN=<token válido>`
- `TELEGRAM_CHAT_ID=<chat_id válido>`
- `APP_ENV=aws` (o no configurado, se detecta automáticamente)

### Paso 2: Revisar Logs del Gatekeeper

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_alert_pipeline_remote.sh TON_USDT 30
```

**Buscar en los logs:**
1. `[ALERT_DECISION]` → ¿Aparece? Si no, la alerta nunca llegó a emit_alert
2. `[ALERT_SKIP]` → Si aparece, `dry_run=True` está bloqueando
3. `[ALERT_ENQUEUED]` → ¿Aparece? Si no, hay error en emit_alert
4. `[LIVE_ALERT_GATEKEEPER]` → Muestra `allowed=True/False` y por qué
5. `[TELEGRAM_SEND]` → Si aparece, se intentó enviar
6. `[TELEGRAM_ERROR]` → Si aparece, la API de Telegram falló

### Paso 3: Verificar Estado del Telegram Notifier

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since=10m 2>&1 | grep -E "(Telegram disabled|E2E_TEST_CONFIG|LIVE_ALERT_GATEKEEPER)" | tail -20'
```

---

## Casos Comunes de Bloqueo

### Caso 1: Origin Incorrecto
**Síntoma:** Logs muestran `[TG_LOCAL_DEBUG] Skipping Telegram send`
**Causa:** `origin != "AWS"` y `!= "TEST"`
**Solución:** Verificar que `get_runtime_origin()` retorna "AWS" en producción

### Caso 2: RUN_TELEGRAM Deshabilitado
**Síntoma:** Logs muestran `Telegram disabled via RUN_TELEGRAM flag`
**Causa:** `RUN_TELEGRAM != "true"`
**Solución:** Configurar `RUN_TELEGRAM=true` en el entorno

### Caso 3: Variables de Entorno Faltantes
**Síntoma:** Logs muestran `Telegram disabled: missing env vars`
**Causa:** `TELEGRAM_BOT_TOKEN` o `TELEGRAM_CHAT_ID` no configurados
**Solución:** Configurar ambas variables en el entorno

### Caso 4: Dry Run Activado
**Síntoma:** Logs muestran `[ALERT_SKIP] (dry run, not sent)`
**Causa:** `settings.ALERTS_DRY_RUN = True`
**Solución:** Verificar configuración de `ALERTS_DRY_RUN` en settings

### Caso 5: Error en API de Telegram
**Síntoma:** Logs muestran `[TELEGRAM_ERROR]`
**Causa:** Error en la llamada HTTP a la API de Telegram
**Solución:** Revisar status code y error body en los logs

---

## Comandos de Diagnóstico Rápido

### Verificar estado completo del sistema de alertas:

```bash
cd /Users/carloscruz/automated-trading-platform

# 1. Ver configuración
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose exec backend-aws env | grep -E "(RUN_TELEGRAM|TELEGRAM|APP_ENV)"'

# 2. Ver logs del gatekeeper
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since=30m 2>&1 | grep -E "LIVE_ALERT_GATEKEEPER" | tail -10'

# 3. Ver intentos de envío
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since=30m 2>&1 | grep -E "TELEGRAM_SEND|TELEGRAM_ERROR" | tail -10'

# 4. Ver decisiones de alertas
bash scripts/debug_alert_pipeline_remote.sh TON_USDT 30
```

---

## Resumen de Puntos de Bloqueo

| Punto | Condición | Log de Bloqueo | Solución |
|-------|-----------|----------------|----------|
| **1. Origin Gatekeeper** | `origin != "AWS"` y `!= "TEST"` | `[TG_LOCAL_DEBUG]` | Verificar `get_runtime_origin()` |
| **2. RUN_TELEGRAM** | `RUN_TELEGRAM != "true"` | `Telegram disabled via RUN_TELEGRAM` | Configurar `RUN_TELEGRAM=true` |
| **3. Env Vars** | Faltan `TELEGRAM_BOT_TOKEN` o `TELEGRAM_CHAT_ID` | `Telegram disabled: missing env vars` | Configurar ambas variables |
| **4. Dry Run** | `ALERTS_DRY_RUN = True` | `[ALERT_SKIP]` | Desactivar dry run |
| **5. API Error** | Error HTTP en Telegram API | `[TELEGRAM_ERROR]` | Revisar token, chat_id, conectividad |

---

## Estado Actual del Código

✅ **Implementado:**
- Gatekeeper de origen (AWS/TEST permitidos, LOCAL bloqueado)
- Logging completo en cada punto del pipeline
- Script de debug para rastrear alertas
- Función `emit_alert` centralizada

⚠️ **Pendiente de Verificar:**
- Configuración de `RUN_TELEGRAM` en AWS
- Variables de entorno `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`
- Valor de `ALERTS_DRY_RUN` en settings
- Que `get_runtime_origin()` retorne "AWS" en producción

---

## Próximos Pasos

1. Ejecutar diagnóstico completo con los comandos arriba
2. Verificar configuración en AWS
3. Revisar logs para identificar el punto exacto de bloqueo
4. Corregir la configuración según el diagnóstico

