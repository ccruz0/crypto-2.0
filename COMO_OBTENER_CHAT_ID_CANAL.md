# Cómo Obtener el Chat ID del Canal "Hilovivo-alerts"

## Método 1: Usando @userinfobot (MÁS FÁCIL) ⭐

### Paso 1: Abre Telegram
- Abre la app de Telegram en tu teléfono o computadora

### Paso 2: Ve al canal "Hilovivo-alerts"
- Busca el canal "Hilovivo-alerts" en Telegram
- Ábrelo

### Paso 3: Busca @userinfobot
- En la barra de búsqueda de Telegram, escribe: `@userinfobot`
- Abre el bot (debería aparecer como "User Info Bot")

### Paso 4: Reenvía un mensaje del canal
- En el canal "Hilovivo-alerts", selecciona cualquier mensaje
- Toca el botón de "Reenviar" (flecha hacia adelante)
- Selecciona `@userinfobot` como destinatario
- Envía el mensaje reenviado

### Paso 5: Obtén el Chat ID
- El bot `@userinfobot` te responderá con información del canal
- Busca el campo que dice algo como:
  ```
  Chat ID: -1001234567890
  ```
- **Copia ese número** (será negativo, como `-1001234567890`)

---

## Método 2: Usando la API de Telegram (Alternativo)

Si el método 1 no funciona, puedes usar este:

### Paso 1: Asegúrate de que el bot esté en el canal
- Ve al canal "Hilovivo-alerts"
- Asegúrate de que el bot `Hilovivolocal_bot` esté agregado como administrador
- Si no está, agrégalo como administrador del canal

### Paso 2: Envía un mensaje en el canal
- Escribe cualquier mensaje en el canal "Hilovivo-alerts"
- Esto hará que el bot reciba una actualización

### Paso 3: Ejecuta este comando en AWS
```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
docker compose --profile aws exec backend-aws python3 << 'PYEOF'
import requests
import os
import json

bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
if bot_token:
    url = f'https://api.telegram.org/bot{bot_token}/getUpdates?offset=-50&limit=50'
    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        data = response.json()
        if data.get('ok'):
            updates = data.get('result', [])
            print('Buscando canal "Hilovivo-alerts"...\n')
            for update in updates:
                msg = update.get('message') or update.get('channel_post')
                if msg:
                    chat = msg.get('chat', {})
                    chat_title = chat.get('title', '')
                    chat_id = chat.get('id')
                    chat_type = chat.get('type')
                    
                    if 'Hilovivo' in chat_title or chat_type in ['channel', 'supergroup']:
                        print(f'✅ Canal encontrado:')
                        print(f'   Título: {chat_title}')
                        print(f'   Chat ID: {chat_id}')
                        print(f'   Tipo: {chat_type}')
                        print()
                        if chat_id < 0:
                            print(f'🎯 Chat ID del canal: {chat_id}')
                            break
            else:
                print('⚠️ No se encontró el canal en las actualizaciones recientes')
                print('💡 Asegúrate de:')
                print('   1. El bot está agregado al canal como administrador')
                print('   2. Has enviado un mensaje en el canal recientemente')
PYEOF
```

---

## Una vez que tengas el Chat ID

### Paso 1: Actualiza .env.aws
```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
nano .env.aws
```

### Paso 2: Busca esta línea
```bash
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
```

### Paso 3: Cámbiala por el chat_id del canal
```bash
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
```
(Reemplaza `-1001234567890` con el chat_id real que obtuviste)

### Paso 4: Guarda y sal
- Presiona `Ctrl + X`
- Presiona `Y` para confirmar
- Presiona `Enter` para guardar

### Paso 5: Reinicia el backend
```bash
docker compose --profile aws restart backend-aws
```

### Paso 6: Verifica
```bash
docker compose --profile aws exec backend-aws env | grep TELEGRAM_CHAT_ID
```

Deberías ver:
```
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
```

---

## Verificar que funciona

1. Cambia el `trade_amount_usd` de alguna moneda con señal activa
2. Verifica que la alerta llegue al canal "Hilovivo-alerts" en Telegram
3. Revisa los logs:
```bash
docker compose --profile aws logs backend-aws | grep TELEGRAM_SEND | tail -5
```

Deberías ver algo como:
```
[TELEGRAM_SEND] chat_id=-1001234567890
[TELEGRAM_RESPONSE] status=200 RESULT=SUCCESS
```

---

## Notas Importantes

- ✅ Los canales tienen IDs **negativos** (ejemplo: `-1001234567890`)
- ✅ Los chats privados tienen IDs **positivos** (ejemplo: `839853931`)
- ✅ El bot debe ser **administrador** del canal para enviar mensajes
- ✅ Los cambios requieren **reinicio** del backend para aplicarse








