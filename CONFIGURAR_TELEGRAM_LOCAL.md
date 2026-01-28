# Configurar Telegram en Entorno Local

## Variables Necesarias

Para que las alertas funcionen en el entorno local, necesitas configurar estas variables en `.env.local`:

```bash
APP_ENV=local
TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
```

## Pasos para Configurar

### 1. Obtener el Bot Token

Si ya tienes un bot de Telegram:
- El token debería estar en la configuración del bot
- O puedes obtenerlo de @BotFather en Telegram

### 2. Obtener el Chat ID

Para el canal `hilovivo-alerts-local`:
1. Agrega el bot al canal
2. Envía un mensaje al canal
3. Visita: `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`
4. Busca el `chat.id` del canal (será un número negativo como `-1001234567890`)

O usa este método:
```bash
# Reemplaza <BOT_TOKEN> con tu token
curl https://api.telegram.org/bot<BOT_TOKEN>/getUpdates | jq '.result[].message.chat.id'
```

### 3. Editar .env.local

Abre el archivo `.env.local` y descomenta/actualiza estas líneas:

```bash
APP_ENV=local
TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
```

**⚠️ IMPORTANTE:** 
- Reemplaza los valores de ejemplo con tus valores reales
- El `TELEGRAM_CHAT_ID` debe ser el ID del canal `hilovivo-alerts-local`
- No compartas estos valores públicamente

### 4. Reiniciar el Servicio

Después de actualizar `.env.local`:

```bash
docker compose restart backend
```

### 5. Verificar Configuración

Verifica que las variables se cargaron correctamente:

```bash
docker compose exec backend python3 << 'EOF'
import sys
sys.path.insert(0, '/app')
from app.core.config import settings
from app.services.telegram_notifier import telegram_notifier

print(f"APP_ENV: {settings.APP_ENV}")
print(f"TELEGRAM_BOT_TOKEN: {'✅ Configurado' if settings.TELEGRAM_BOT_TOKEN else '❌ No configurado'}")
print(f"TELEGRAM_CHAT_ID: {'✅ Configurado' if settings.TELEGRAM_CHAT_ID else '❌ No configurado'}")
print(f"Telegram Enabled: {telegram_notifier.enabled}")
EOF
```

## Resultado Esperado

Una vez configurado:
- ✅ Las alertas de BTC_USDT se enviarán con prefijo `[LOCAL]`
- ✅ Los mensajes irán al canal `hilovivo-alerts-local`
- ✅ El SignalMonitorService detectará señales y enviará alertas

## Notas

- Si no configuras `TELEGRAM_BOT_TOKEN` o `TELEGRAM_CHAT_ID`, las alertas no se enviarán pero el sistema seguirá funcionando
- El prefijo `[LOCAL]` se agregará automáticamente a todos los mensajes
- Asegúrate de que el bot tenga permisos para enviar mensajes al canal

