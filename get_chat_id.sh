#!/bin/bash
# Script para obtener el Chat ID del canal de Telegram

BOT_TOKEN="8408220395:AAEJAZcUEy4-9rfEsqKtfR0tHskL4vM4pew"

echo "🔍 Obteniendo Chat ID del canal..."
echo ""

# Obtener updates
RESPONSE=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getUpdates")

# Buscar Chat IDs
echo "📱 Chats encontrados:"
echo ""

# Extraer información de chats
echo "$RESPONSE" | python3 << 'PYTHON'
import sys
import json

try:
    data = json.load(sys.stdin)
    
    if not data.get('ok'):
        print(f"❌ Error: {data.get('description', 'Unknown error')}")
        sys.exit(1)
    
    results = data.get('result', [])
    
    if not results:
        print("⚠️  No se encontraron mensajes.")
        print("")
        print("💡 Para obtener el Chat ID:")
        print("   1. Agrega el bot @Hilovivolocal_bot al canal")
        print("   2. Dale permisos de administrador")
        print("   3. Envía un mensaje al canal")
        print("   4. Ejecuta este script de nuevo")
        sys.exit(0)
    
    chats_found = {}
    
    for update in results:
        if 'message' in update:
            chat = update['message'].get('chat', {})
            chat_id = chat.get('id')
            chat_type = chat.get('type', 'unknown')
            chat_title = chat.get('title') or chat.get('first_name', 'Unknown')
            
            if chat_id:
                key = f"{chat_type}_{chat_id}"
                if key not in chats_found:
                    chats_found[key] = {
                        'id': chat_id,
                        'type': chat_type,
                        'title': chat_title
                    }
    
    if chats_found:
        print("✅ Chats encontrados:")
        print("")
        for chat_info in chats_found.values():
            print(f"   📱 {chat_info['title']}")
            print(f"      Tipo: {chat_info['type']}")
            print(f"      Chat ID: {chat_info['id']}")
            print("")
        
        # Si hay un canal (tipo 'channel' o 'supergroup'), mostrarlo destacado
        channels = [c for c in chats_found.values() if c['type'] in ['channel', 'supergroup']]
        if channels:
            print("🎯 Canal recomendado (para alertas):")
            for channel in channels:
                print(f"   Chat ID: {channel['id']}")
                print(f"   Nombre: {channel['title']}")
    else:
        print("⚠️  No se encontraron chats con ID válido")
        
except json.JSONDecodeError:
    print("❌ Error al parsear la respuesta JSON")
except Exception as e:
    print(f"❌ Error: {e}")
PYTHON

echo ""
echo "💡 Si encontraste el Chat ID, agrégalo a .env.local:"
echo "   TELEGRAM_CHAT_ID=<el_chat_id_que_encontraste>"

