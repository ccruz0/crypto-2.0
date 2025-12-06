#!/usr/bin/env python3
"""
Archivo de configuración para credenciales de Crypto.com API
"""

# INSTRUCCIONES PARA OBTENER TUS CREDENCIALES REALES:
# 1. Ve a https://crypto.com/exchange/private/api
# 2. Crea una API Key con permisos de lectura
# 3. Copia tu API Key y Secret Key aquí
# 4. Reinicia el servidor para que use tus datos reales

# Reemplaza estos valores con tus credenciales reales:
API_KEY = "tu_api_key_aqui"  # Tu API Key de Crypto.com
SECRET_KEY = "tu_secret_key_aqui"  # Tu Secret Key de Crypto.com

# Configuración adicional
BASE_URL = "https://api.crypto.com/v2"
TIMEOUT = 10  # segundos

# Verificar si las credenciales están configuradas
def are_credentials_configured():
    return (API_KEY != "tu_api_key_aqui" and 
            SECRET_KEY != "tu_secret_key_aqui" and 
            API_KEY != "" and 
            SECRET_KEY != "")

if __name__ == "__main__":
    if are_credentials_configured():
        print("✅ Credenciales configuradas correctamente")
    else:
        print("⚠️  Credenciales no configuradas - usando datos mock")
        print("📝 Para obtener datos reales:")
        print("   1. Ve a https://crypto.com/exchange/private/api")
        print("   2. Crea una API Key con permisos de lectura")
        print("   3. Actualiza las credenciales en este archivo")
        print("   4. Reinicia el servidor")

