#!/bin/bash
# Script para configurar un canal nuevo de Telegram

echo "📱 CONFIGURACIÓN DE CANAL NUEVO"
echo ""
echo "Pasos:"
echo "1. Crea un canal nuevo en Telegram (New Channel)"
echo "2. Nombre: 'Hilovivo-alerts' o 'Hilovivo-alerts-AWS'"
echo "3. Agrega el bot @Hilovivolocal_bot como administrador"
echo "4. Dale permisos para 'Post Messages'"
echo "5. Envía un mensaje de prueba en el canal (ej: 'test')"
echo ""
read -p "Presiona Enter cuando hayas completado los pasos 1-5..."

cd /Users/carloscruz/automated-trading-platform
source scripts/ssh_key.sh 2>/dev/null

echo ""
echo "🔍 Capturando chat_id del canal nuevo..."

ssh_cmd hilovivo-aws "cd /home/ubuntu/automated-trading-platform && BOT_TOKEN=\$(grep '^TELEGRAM_BOT_TOKEN=' .env.aws | cut -d= -f2) && curl -s \"https://api.telegram.org/bot\${BOT_TOKEN}/getUpdates?offset=-5\" > /tmp/new_channel.json && python3 << 'PYEOF'
import json
from datetime import datetime

with open('/tmp/new_channel.json', 'r') as f:
    data = json.load(f)

if data.get('ok'):
    updates = data.get('result', [])
    current_time = int(datetime.now().timestamp())
    
    channels = {}
    for update in reversed(updates):
        msg = update.get('channel_post') or update.get('message', {})
        if not msg:
            continue
            
        update_time = msg.get('date', 0)
        if current_time - update_time <= 120:  # Últimos 2 minutos
            chat = msg.get('chat', {})
            if chat.get('type') == 'channel':
                chat_id = chat.get('id')
                title = chat.get('title', '')
                if chat_id and chat_id < 0:
                    channels[chat_id] = title
    
    if channels:
        print('✅ Canales encontrados:')
        for chat_id, title in channels.items():
            print(f'   Chat ID: {chat_id}')
            print(f'   Título: {title}')
        
        selected_id = list(channels.keys())[0]  # El más reciente
        
        print()
        print('=' * 60)
        print(f'🎯 Chat ID del canal: {selected_id}')
        print()
        print('📝 Actualizando .env.aws...')
        
        import subprocess
        result = subprocess.run(['sed', '-i', f's|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID={selected_id}|', '/home/ubuntu/automated-trading-platform/.env.aws'])
        
        if result.returncode == 0:
            print(f'✅ Actualizado: TELEGRAM_CHAT_ID={selected_id}')
            print()
            print('🔄 Reiniciando servicios...')
            subprocess.run(['docker', 'compose', '--profile', 'aws', 'restart', 'backend-aws', 'market-updater-aws'], capture_output=True)
            print('✅ Servicios reiniciados')
            print()
            print('🧪 Enviando mensaje de prueba...')
            import sys
            sys.path.insert(0, '/app')
            from app.services.telegram_notifier import telegram_notifier
            test_result = telegram_notifier.send_message('🧪 Canal configurado correctamente!')
            if test_result:
                print('✅ ¡Mensaje de prueba enviado al canal!')
            else:
                print('⚠️  Error al enviar mensaje de prueba')
        else:
            print('❌ Error al actualizar .env.aws')
    else:
        print('⚠️  No se encontró el canal')
        print('   Asegúrate de haber enviado el mensaje hace menos de 2 minutos')
else:
    print(f'❌ Error: {data.get(\"description\", \"Unknown\")}')
PYEOF
"

echo ""
echo "✅ Proceso completado"







