# Fix: Notificaciones de Telegram para SL/TP no se enviaban

## Problema Identificado

No recibiste notificación en Telegram cuando se crearon las órdenes SL/TP de SOL_USD porque:

### 1. **`send_sl_tp_orders` no pasaba el parámetro `origin`**

El método `send_sl_tp_orders()` llamaba a `send_message()` sin el parámetro `origin`, lo que causaba que:
- Si `RUNTIME_ORIGIN` no estaba configurado como "AWS", el gatekeeper bloqueaba la notificación
- El sistema asumía `origin="LOCAL"` por defecto, bloqueando el envío

### 2. **Gatekeeper de Telegram**

El sistema tiene un gatekeeper que **solo permite** notificaciones cuando:
- `origin == "AWS"` o `origin == "TEST"`
- `RUNTIME_ORIGIN=AWS` está configurado en el servicio
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` están configurados

## Solución Implementada

✅ **Corregido en:** `backend/app/services/telegram_notifier.py`

**Cambio realizado:**
```python
# ANTES (línea 902):
return self.send_message(message.strip())

# DESPUÉS:
from app.core.runtime import get_runtime_origin
origin = get_runtime_origin()  # Will be "AWS" if RUNTIME_ORIGIN=AWS is set
return self.send_message(message.strip(), origin=origin)
```

Ahora `send_sl_tp_orders()` pasa explícitamente el `origin` correcto a `send_message()`, asegurando que:
- Si `RUNTIME_ORIGIN=AWS` está configurado → `origin="AWS"` → ✅ Notificación se envía
- Si `RUNTIME_ORIGIN` no está configurado → `origin="LOCAL"` → ❌ Notificación bloqueada (por seguridad)

## Verificación de Configuración

### ✅ Configuración en `docker-compose.yml` (CORRECTA)

El servicio `backend-aws` tiene configurado:
```yaml
backend-aws:
  environment:
    - RUNTIME_ORIGIN=AWS  # ✅ Correcto
    - RUN_TELEGRAM=${RUN_TELEGRAM:-true}
  env_file:
    - .env.aws  # Debe contener TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID
```

### Verificar Variables de Entorno

Para verificar que las variables están configuradas correctamente:

```bash
# Verificar variables en el contenedor
docker compose --profile aws exec backend-aws env | grep -E "RUNTIME_ORIGIN|TELEGRAM"

# Debería mostrar:
# RUNTIME_ORIGIN=AWS
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...
```

## Próximos Pasos

1. **Reiniciar el servicio backend-aws** para aplicar el fix:
   ```bash
   docker compose --profile aws restart backend-aws
   ```

2. **Verificar logs** después de que se creen nuevas órdenes SL/TP:
   ```bash
   docker compose --profile aws logs -f backend-aws | grep -i "sl/tp\|telegram"
   ```

3. **Buscar en logs históricos** si se intentó enviar la notificación:
   ```bash
   docker compose --profile aws logs backend-aws | grep -i "telegram.*blocked\|gatekeeper.*block\|send_sl_tp"
   ```

## Notas Importantes

- **Las notificaciones futuras funcionarán** con este fix
- **Las notificaciones pasadas no se pueden recuperar** (ya se perdieron)
- **El fix asegura** que todas las notificaciones de SL/TP futuras se envíen correctamente

## Flujo Corregido

```
1. Orden BUY ejecutada → exchange_sync detecta FILLED
2. _create_sl_tp_for_filled_order() crea SL/TP
3. send_sl_tp_orders() → send_message(origin=get_runtime_origin())
4. get_runtime_origin() → "AWS" (si RUNTIME_ORIGIN=AWS configurado)
5. Gatekeeper verifica origin="AWS" → ✅ PERMITE
6. Notificación enviada a Telegram ✅
```

## Diagnóstico

Si aún no recibes notificaciones después del fix, verifica:

1. **RUNTIME_ORIGIN está configurado:**
   ```bash
   docker compose --profile aws exec backend-aws env | grep RUNTIME_ORIGIN
   ```

2. **Telegram está habilitado:**
   ```bash
   docker compose --profile aws exec backend-aws env | grep RUN_TELEGRAM
   ```

3. **Token y Chat ID están configurados:**
   ```bash
   docker compose --profile aws exec backend-aws env | grep TELEGRAM
   ```

4. **Revisar logs de errores:**
   ```bash
   docker compose --profile aws logs backend-aws | grep -i "error.*telegram\|failed.*notification"
   ```







