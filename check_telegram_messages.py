#!/usr/bin/env python3
"""Script to check the last 3 Telegram messages sent by the bot"""
import subprocess
import re
from datetime import datetime

def get_telegram_messages():
    """Get the last Telegram messages from Docker logs"""
    try:
        # Get the last 1000 lines of backend logs
        result = subprocess.run(
            ['docker', 'compose', 'logs', '--tail=1000', 'backend'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"Error getting logs: {result.stderr}")
            return []
        
        lines = result.stdout.split('\n')
        
        # Pattern to match Telegram-related log entries
        telegram_patterns = [
            r'Telegram message sent',
            r'\[TG\]',
            r'\[TELEGRAM\]',
            r'send_message',
            r'BUY ORDER',
            r'SELL ORDER',
            r'ORDER CREATED',
            r'ORDER EXECUTED',
            r'SL/TP ORDERS',
            r'BUY SIGNAL',
            r'SELL SIGNAL',
            r'PROTECCIÓN ACTIVADA',
        ]
        
        telegram_messages = []
        
        for line in lines:
            # Check if line contains any Telegram pattern
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in telegram_patterns):
                # Try to extract timestamp and message
                # Docker log format: container_name | timestamp | message
                parts = line.split('|', 2)
                if len(parts) >= 3:
                    timestamp = parts[1].strip() if len(parts) > 1 else "N/A"
                    message = parts[2].strip()
                else:
                    timestamp = "N/A"
                    message = line
                
                telegram_messages.append({
                    'timestamp': timestamp,
                    'message': message,
                    'full_line': line
                })
        
        return telegram_messages[-3:] if len(telegram_messages) >= 3 else telegram_messages
        
    except subprocess.TimeoutExpired:
        print("Timeout getting logs")
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []

def main():
    print("🔍 Buscando los últimos 3 mensajes enviados por Telegram...\n")
    
    messages = get_telegram_messages()
    
    if not messages:
        print("❌ No se encontraron mensajes de Telegram en los logs recientes.")
        print("\n💡 Intenta:")
        print("   1. Verificar que el backend esté corriendo: docker compose ps")
        print("   2. Ver logs directamente: docker compose logs --tail=100 backend | grep -i telegram")
        return
    
    print(f"📨 Últimos {len(messages)} mensajes de Telegram encontrados:\n")
    print("=" * 80)
    
    for i, msg in enumerate(messages, 1):
        print(f"\n📩 Mensaje #{i}")
        print(f"⏰ Timestamp: {msg['timestamp']}")
        print(f"💬 Contenido:")
        print("-" * 80)
        # Extract the actual message content (remove log prefixes)
        content = msg['message']
        # Try to extract HTML/message content if present
        if '<b>' in content or 'ORDER' in content or 'SIGNAL' in content:
            # This looks like a Telegram message content
            print(content)
        else:
            print(content)
        print("-" * 80)
    
    print("\n" + "=" * 80)
    print(f"\n✅ Total: {len(messages)} mensaje(s) encontrado(s)")

if __name__ == "__main__":
    main()

