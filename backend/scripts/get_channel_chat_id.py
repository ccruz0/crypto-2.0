#!/usr/bin/env python3
"""
Script para obtener el chat_id del canal "Hilovivo-alerts"
"""
import sys
import os
import json
import requests

# Obtener el bot token desde el archivo .env.aws
def get_bot_token():
    """Obtener el bot token desde .env.aws"""
    env_file = os.path.expanduser("~/.env.aws")
    if not os.path.exists(env_file):
        # Intentar desde el directorio del proyecto
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.aws")
        if not os.path.exists(env_file):
            env_file = "/home/ubuntu/crypto-2.0/.env.aws"
    
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                if line.startswith('TELEGRAM_BOT_TOKEN='):
                    return line.split('=', 1)[1].strip()
    
    # Intentar desde variables de entorno
    return os.getenv('TELEGRAM_BOT_TOKEN', '')

def get_channel_chat_id(bot_token):
    """Obtener el chat_id del canal desde los updates de Telegram"""
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    
    print("🔍 Buscando el chat_id del canal 'Hilovivo-alerts'...")
    print()
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data.get('ok'):
            print(f"❌ Error de la API: {data.get('description', 'Unknown error')}")
            return None
        
        updates = data.get('result', [])
        
        if not updates:
            print("⚠️  No hay updates recientes.")
            print()
            print("📝 Para obtener el chat_id del canal:")
            print("   1. Ve al canal 'Hilovivo-alerts' en Telegram")
            print("   2. Asegúrate de que el bot esté agregado como administrador")
            print("   3. Envía un mensaje en el canal (o reenvía un mensaje existente)")
            print("   4. Ejecuta este script de nuevo")
            print()
            return None
        
        # Buscar en los updates
        channel_ids = {}
        for update in updates:
            # Buscar en channel_post (mensajes del canal)
            if 'channel_post' in update:
                chat = update['channel_post'].get('chat', {})
                if chat.get('type') == 'channel':
                    chat_id = chat.get('id')
                    title = chat.get('title', 'N/A')
                    if 'Hilovivo' in title or 'hilovivo' in title.lower():
                        channel_ids[chat_id] = title
        
        # Buscar en message (si el bot recibió un mensaje del canal)
        for update in updates:
            if 'message' in update:
                chat = update['message'].get('chat', {})
                if chat.get('type') == 'channel':
                    chat_id = chat.get('id')
                    title = chat.get('title', 'N/A')
                    if 'Hilovivo' in title or 'hilovivo' in title.lower():
                        channel_ids[chat_id] = title
        
        if channel_ids:
            print("✅ Canales encontrados:")
            print()
            for chat_id, title in channel_ids.items():
                print(f"   Chat ID: {chat_id}")
                print(f"   Título: {title}")
                print()
            return list(channel_ids.keys())[0]
        else:
            print("⚠️  No se encontró el canal 'Hilovivo-alerts' en los updates.")
            print()
            print("📝 Pasos para obtener el chat_id:")
            print("   1. Ve al canal 'Hilovivo-alerts' en Telegram")
            print("   2. Asegúrate de que el bot esté agregado como administrador")
            print("   3. Envía cualquier mensaje en el canal")
            print("   4. Ejecuta este script de nuevo")
            print()
            print("💡 Alternativa: Usa @userinfobot")
            print("   - Reenvía un mensaje del canal a @userinfobot")
            print("   - Te mostrará el chat_id del canal")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al conectar con la API de Telegram: {e}")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

if __name__ == "__main__":
    bot_token = get_bot_token()
    
    if not bot_token:
        print("❌ No se encontró TELEGRAM_BOT_TOKEN")
        print("   Asegúrate de que esté configurado en .env.aws")
        sys.exit(1)
    
    chat_id = get_channel_chat_id(bot_token)
    
    if chat_id:
        print("=" * 60)
        print(f"✅ Chat ID del canal: {chat_id}")
        print()
        print("📝 Para actualizar .env.aws:")
        print(f"   TELEGRAM_CHAT_ID={chat_id}")
        print()
    else:
        sys.exit(1)







