# Obtener Chat ID del Canal "Hilovivo-alerts"

Veo que estás en el canal "Hilovivo-alerts" y el bot ya está agregado. Aquí tienes las opciones:

## Método 1: Enviar un mensaje en el canal (RECOMENDADO)

1. **En el canal "Hilovivo-alerts", escribe cualquier mensaje** (por ejemplo: "test")
2. **Envía el mensaje**
3. **Espera 5 segundos**
4. **Luego ejecuta este comando:**
   ```bash
   ssh hilovivo-aws
   cd /home/ubuntu/automated-trading-platform
   docker compose --profile aws exec backend-aws python3 << 'PYEOF'
   import requests
   import os
   bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
   url = f'https://api.telegram.org/bot{bot_token}/getUpdates?offset=-10&limit=10'
   response = requests.get(url, timeout=10)
   data = response.json()
   for update in data.get('result', []):
       if 'message' in update:
           chat = update['message'].get('chat', {})
           if 'Hilovivo' in chat.get('title', ''):
               print(f"Chat ID: {chat['id']}")
               print(f"Title: {chat.get('title', 'N/A')}")
   PYEOF
   ```

## Método 2: Usar @userinfobot desde el canal

1. **En el canal "Hilovivo-alerts"**, busca cualquier mensaje
2. **Mantén presionado el mensaje** → Selecciona "Reenviar"
3. **Reenvía a @userinfobot**
4. El bot te mostrará el Chat ID del canal (número negativo)

## Método 3: Ver información del grupo en Telegram

1. **En el canal "Hilovivo-alerts"**, toca el nombre del grupo en la parte superior
2. **Ve a "Info" o configuración del grupo**
3. Algunas veces Telegram muestra el Chat ID allí

## Una vez que tengas el Chat ID (número negativo)

Actualiza `.env.aws`:

```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
nano .env.aws
```

Cambia:
```bash
TELEGRAM_CHAT_ID=839853931
```

Por:
```bash
TELEGRAM_CHAT_ID=-1001234567890  # (el número negativo que obtuviste)
```

Luego reinicia:
```bash
docker compose --profile aws restart backend-aws
```


