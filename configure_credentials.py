#!/usr/bin/env python3
"""
Script para configurar credenciales de Crypto.com API
"""

import os
import sys

def configure_credentials():
    print("🔐 Configuración de Credenciales de Crypto.com API")
    print("=" * 50)
    print()
    print("Para obtener tus datos reales de trading, necesitas configurar tus credenciales de Crypto.com API.")
    print()
    print("📋 PASOS PARA OBTENER CREDENCIALES:")
    print("1. Ve a https://crypto.com/exchange/private/api")
    print("2. Inicia sesión en tu cuenta de Crypto.com")
    print("3. Crea una nueva API Key con los siguientes permisos:")
    print("   ✅ Read (Lectura)")
    print("   ❌ Trade (Trading) - NO marcar por seguridad")
    print("   ❌ Withdraw (Retiros) - NO marcar por seguridad")
    print("4. Copia tu API Key y Secret Key")
    print()
    
    # Solicitar credenciales
    api_key = input("🔑 Ingresa tu API Key: ").strip()
    secret_key = input("🔐 Ingresa tu Secret Key: ").strip()
    
    if not api_key or not secret_key:
        print("❌ Credenciales no proporcionadas")
        return False
    
    # Actualizar el archivo del servidor
    try:
        with open('corrected_trading_server.py', 'r') as f:
            content = f.read()
        
        # Reemplazar las credenciales
        content = content.replace('API_KEY = "tu_api_key_aqui"', f'API_KEY = "{api_key}"')
        content = content.replace('SECRET_KEY = "tu_secret_key_aqui"', f'SECRET_KEY = "{secret_key}"')
        
        with open('corrected_trading_server.py', 'w') as f:
            f.write(content)
        
        print("✅ Credenciales configuradas correctamente")
        print("🔄 Reinicia el servidor para usar tus datos reales")
        return True
        
    except Exception as e:
        print(f"❌ Error configurando credenciales: {e}")
        return False

def test_credentials():
    """Probar si las credenciales están configuradas"""
    try:
        with open('corrected_trading_server.py', 'r') as f:
            content = f.read()
        
        if 'tu_api_key_aqui' in content or 'tu_secret_key_aqui' in content:
            return False
        return True
    except:
        return False

if __name__ == "__main__":
    if test_credentials():
        print("✅ Credenciales ya configuradas")
        print("🔄 Para reiniciar el servidor con datos reales:")
        print("   pkill -f corrected_trading_server.py")
        print("   python3 corrected_trading_server.py")
    else:
        configure_credentials()

