#!/bin/bash
# Script para obtener el chat_id del canal inmediatamente después de enviar un mensaje

echo "📱 OBTENER CHAT_ID DEL CANAL"
echo ""
echo "INSTRUCCIONES:"
echo "1. Ve al canal 'Hilovivo-alerts' en Telegram"
echo "2. Envía un mensaje de prueba en el canal (ej: 'test')"
echo "3. INMEDIATAMENTE después, presiona Enter aquí"
echo ""
read -p "Presiona Enter DESPUÉS de enviar el mensaje en el canal..."

cd /Users/carloscruz/automated-trading-platform
source scripts/ssh_key.sh 2>/dev/null

ssh_cmd hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec -T backend-aws python3 << 'PYEOF'
import os
import requests
import time

bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
url = f'https://api.telegram.org/bot{bot_token}/getUpdates?offset=-5'

response = requests.get(url, timeout=10)
data = response.json()

if data.get('ok'):
    updates = data.get('result', [])
    for update in reversed(updates):
        msg = update.get('channel_post') or update.get('message', {})
        chat = msg.get('chat', {})
        if chat.get('type') == 'channel':
            chat_id = chat.get('id')
            title = chat.get('title', '')
            if chat_id and chat_id < 0:
                print(f'✅ Chat ID encontrado: {chat_id}')
                print(f'   Título: {title}')
                print()
                print('📝 Actualizando .env.aws...')
                import subprocess
                subprocess.run(['sed', '-i', f's|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID={chat_id}|', '/home/ubuntu/automated-trading-platform/.env.aws'])
                print(f'✅ Actualizado: TELEGRAM_CHAT_ID={chat_id}')
                exit(0)

print('⚠️  No se encontró el canal. Asegúrate de haber enviado el mensaje.')
PYEOF
"

echo ""
echo "🔄 Reiniciando servicios..."
ssh_cmd hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws market-updater-aws"

echo ""
echo "✅ ¡Listo! El chat_id ha sido actualizado y los servicios reiniciados."



