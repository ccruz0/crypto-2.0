#!/bin/bash
# Script para capturar el chat_id del canal después de enviar un mensaje

echo "🔍 Capturando chat_id del canal..."
echo ""

cd /Users/carloscruz/crypto-2.0
source scripts/ssh_key.sh 2>/dev/null

ssh_cmd hilovivo-aws "cd /home/ubuntu/crypto-2.0 && docker compose --profile aws exec -T backend-aws python3 << 'PYEOF'
import os
import requests
import time
import subprocess

bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
if not bot_token:
    print('❌ TELEGRAM_BOT_TOKEN no encontrado')
    exit(1)

print('🔍 Buscando mensajes recientes del canal (últimos 60 segundos)...')
print()

url = f'https://api.telegram.org/bot{bot_token}/getUpdates?offset=-10'
try:
    response = requests.get(url, timeout=10)
    data = response.json()
    
    if data.get('ok'):
        updates = data.get('result', [])
        current_time = int(time.time())
        
        channels = {}
        for update in reversed(updates):
            msg = update.get('channel_post') or update.get('message', {})
            update_time = msg.get('date', 0)
            
            # Solo mensajes de los últimos 60 segundos
            if current_time - update_time <= 60:
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
            print()
            
            # Seleccionar el canal (el que tenga Hilovivo o el único encontrado)
            selected_id = None
            for chat_id, title in channels.items():
                if 'Hilovivo' in title or 'hilovivo' in title.lower():
                    selected_id = chat_id
                    break
            
            if not selected_id and len(channels) == 1:
                selected_id = list(channels.keys())[0]
            
            if selected_id:
                print('=' * 60)
                print(f'🎯 Chat ID del canal: {selected_id}')
                print()
                print('📝 Actualizando .env.aws...')
                
                # Actualizar .env.aws
                env_file = '/home/ubuntu/crypto-2.0/.env.aws'
                result = subprocess.run(
                    ['sed', '-i', f's|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID={selected_id}|', env_file],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    print(f'✅ Actualizado: TELEGRAM_CHAT_ID={selected_id}')
                    print()
                    print('🔄 Reiniciando servicios...')
                    subprocess.run(['docker', 'compose', '--profile', 'aws', 'restart', 'backend-aws', 'market-updater-aws'], 
                                  capture_output=True)
                    print('✅ Servicios reiniciados')
                    print()
                    print('🧪 Enviando mensaje de prueba...')
                    from app.services.telegram_notifier import telegram_notifier
                    test_result = telegram_notifier.send_message('🧪 Mensaje de prueba - Configuración actualizada!')
                    if test_result:
                        print('✅ ¡Mensaje de prueba enviado exitosamente al canal!')
                    else:
                        print('⚠️  El mensaje no se pudo enviar')
                else:
                    print(f'❌ Error al actualizar: {result.stderr}')
            else:
                print('⚠️  Se encontraron canales pero no se pudo determinar cuál es el correcto')
        else:
            print('⚠️  No se encontraron mensajes recientes del canal')
            print()
            print('💡 Asegúrate de:')
            print('   1. Haber enviado el mensaje en el canal hace menos de 60 segundos')
            print('   2. Que el bot esté agregado al canal como administrador')
            print('   3. Ejecutar este script inmediatamente después de enviar el mensaje')
            
except Exception as e:
    print(f'❌ Error: {e}')
PYEOF
"

echo ""
echo "✅ Proceso completado"







