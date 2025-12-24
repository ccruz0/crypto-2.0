#!/bin/bash
# Script para verificar Telegram cuando envías /start

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     🔍 VERIFICACIÓN TELEGRAM - ENVÍA /start AHORA           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 INSTRUCCIONES:"
echo "   1. Abre Telegram"
echo "   2. Envía /start en el grupo o chat privado"
echo "   3. Espera 3 segundos"
echo ""
echo "⏳ Esperando 10 segundos para que envíes /start..."
sleep 10

echo ""
echo "🔍 Verificando updates disponibles..."
docker compose --profile aws exec backend-aws python -c "
import requests
import os
bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
if bot_token:
    url = f'https://api.telegram.org/bot{bot_token}/getUpdates'
    params = {'limit': 10, 'timeout': 0}
    response = requests.get(url, params=params, timeout=5)
    data = response.json()
    if data.get('ok'):
        updates = data.get('result', [])
        if updates:
            print(f'✅ Encontrados {len(updates)} updates:')
            for u in updates:
                if 'message' in u:
                    msg = u['message']
                    text = msg.get('text', '')
                    chat = msg.get('chat', {})
                    from_user = msg.get('from', {})
                    print(f'  Update {u.get(\"update_id\")}:')
                    print(f'    Texto: {text}')
                    print(f'    Chat ID: {chat.get(\"id\")} ({chat.get(\"type\")})')
                    print(f'    Chat Title: {chat.get(\"title\", \"Private\")}')
                    print(f'    User ID: {from_user.get(\"id\")}')
                    print()
        else:
            print('⚠️  No hay updates disponibles')
            print('   (Pueden haber sido consumidos ya)')
    else:
        print(f'❌ Error: {data}')
"

echo ""
echo "📊 Revisando logs recientes..."
docker compose --profile aws logs --tail=50 backend-aws 2>/dev/null | grep -iE "start|AUTH|DENY|Processing|chat_id.*user_id" | tail -10

echo ""
echo "✅ Verificación completa"

