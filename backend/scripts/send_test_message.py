#!/usr/bin/env python3
"""
Script simple para enviar un mensaje de prueba a Telegram
"""
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.telegram_notifier import telegram_notifier
from app.core.runtime import get_runtime_origin

def main():
    """Envía un mensaje de prueba a Telegram"""
    
    print("=" * 70)
    print("📤 ENVIANDO MENSAJE DE PRUEBA A TELEGRAM")
    print("=" * 70)
    print()
    
    # Verificar configuración
    runtime_origin = get_runtime_origin()
    print(f"📍 Runtime Origin: {runtime_origin}")
    print(f"✅ Telegram Habilitado: {telegram_notifier.enabled}")
    print(f"🔑 Bot Token: {'✅ Configurado' if telegram_notifier.bot_token else '❌ No configurado'}")
    print(f"💬 Chat ID: {'✅ Configurado' if telegram_notifier.chat_id else '❌ No configurado'}")
    print()
    
    if not telegram_notifier.enabled:
        print("❌ ERROR: Telegram está deshabilitado")
        print("   Verifica:")
        print("   - RUN_TELEGRAM=true")
        print("   - TELEGRAM_BOT_TOKEN está configurado")
        print("   - TELEGRAM_CHAT_ID está configurado")
        return 1
    
    # Crear mensaje de prueba
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    test_message = f"""🧪 **MENSAJE DE PRUEBA**

Este es un mensaje de prueba del sistema de trading.

✅ **Estado del Sistema:**
   • Origen: {runtime_origin}
   • Timestamp: {timestamp}
   • Sistema funcionando correctamente

Si recibes este mensaje, la configuración de Telegram está correcta.

🤖 Trading Bot Automático"""
    
    print("📝 Mensaje a enviar:")
    print("-" * 70)
    print(test_message)
    print("-" * 70)
    print()
    
    print("📤 Enviando mensaje...")
    
    # Enviar mensaje
    success = telegram_notifier.send_message(test_message, origin=runtime_origin)
    
    if success:
        print()
        print("=" * 70)
        print("✅ ¡ÉXITO! Mensaje enviado correctamente")
        print("=" * 70)
        print()
        print("💡 Verifica tu chat de Telegram para confirmar la recepción.")
        return 0
    else:
        print()
        print("=" * 70)
        print("❌ ERROR: No se pudo enviar el mensaje")
        print("=" * 70)
        print()
        print("🔍 Posibles causas:")
        print("   • RUNTIME_ORIGIN no está configurado como 'AWS'")
        print("   • Credenciales de Telegram incorrectas")
        print("   • Problemas de conexión con la API de Telegram")
        print()
        print("📋 Verifica los logs para más detalles.")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)















