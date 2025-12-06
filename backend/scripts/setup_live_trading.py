#!/usr/bin/env python3
"""
Script para configurar y verificar LIVE trading con Crypto.com Exchange
"""

import os
import sys
import requests
import json
from pathlib import Path

def get_current_ip():
    """Obtener IP pública actual"""
    try:
        response = requests.get("https://api.ipify.org", timeout=5)
        return response.text.strip()
    except Exception as e:
        print(f"⚠️  No se pudo obtener IP pública: {e}")
        return None

def check_env_file():
    """Verificar archivo .env.local"""
    env_path = Path(__file__).parent.parent.parent / ".env.local"
    
    if not env_path.exists():
        print("❌ Archivo .env.local no encontrado")
        print(f"📝 Creando archivo .env.local...")
        return {}
    
    print(f"✅ Archivo .env.local encontrado: {env_path}")
    
    # Leer configuración actual
    env_vars = {}
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    
    print("\n📋 Configuración actual:")
    print(f"   LIVE_TRADING: {env_vars.get('LIVE_TRADING', 'no configurado')}")
    print(f"   USE_CRYPTO_PROXY: {env_vars.get('USE_CRYPTO_PROXY', 'no configurado')}")
    print(f"   EXCHANGE_CUSTOM_API_KEY: {'configurado' if env_vars.get('EXCHANGE_CUSTOM_API_KEY') and env_vars.get('EXCHANGE_CUSTOM_API_KEY') != 'tu_api_key_aqui' else 'no configurado'}")
    print(f"   EXCHANGE_CUSTOM_API_SECRET: {'configurado' if env_vars.get('EXCHANGE_CUSTOM_API_SECRET') and env_vars.get('EXCHANGE_CUSTOM_API_SECRET') != 'tu_api_secret_aqui' else 'no configurado'}")
    
    return env_vars

def interactive_setup():
    """Configuración interactiva"""
    print("\n" + "="*60)
    print("🔧 CONFIGURACIÓN DE LIVE TRADING")
    print("="*60)
    print()
    
    # Obtener IP pública
    current_ip = get_current_ip()
    if current_ip:
        print(f"🌐 Tu IP pública actual: {current_ip}")
        print("⚠️  IMPORTANTE: Esta IP debe estar en la whitelist de tu API Key en Crypto.com Exchange")
        print()
    
    # Pedir credenciales
    print("📝 Ingresa tus credenciales de Crypto.com Exchange:")
    print("   (Puedes obtenerlas en: https://exchange.crypto.com/ → Settings → API Keys)")
    print()
    
    api_key = input("🔑 API Key: ").strip()
    api_secret = input("🔐 API Secret: ").strip()
    
    if not api_key or not api_secret:
        print("❌ Credenciales no proporcionadas. Cancelando.")
        return False
    
    # Actualizar .env.local
    env_path = Path(__file__).parent.parent.parent / ".env.local"
    
    # Leer archivo existente si existe
    lines = []
    if env_path.exists():
        with open(env_path, 'r') as f:
            lines = f.readlines()
    
    # Actualizar o añadir variables
    updated_vars = {
        'LIVE_TRADING': 'true',
        'USE_CRYPTO_PROXY': 'false',
        'EXCHANGE_CUSTOM_API_KEY': api_key,
        'EXCHANGE_CUSTOM_API_SECRET': api_secret,
        'EXCHANGE_CUSTOM_BASE_URL': 'https://api.crypto.com/exchange/v1'
    }
    
    # Buscar y reemplazar o añadir
    existing_keys = set()
    new_lines = []
    for line in lines:
        line_stripped = line.strip()
        if line_stripped and not line_stripped.startswith('#') and '=' in line_stripped:
            key = line_stripped.split('=', 1)[0].strip()
            existing_keys.add(key)
            if key in updated_vars:
                new_lines.append(f"{key}={updated_vars[key]}\n")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    # Añadir variables que no existen
    for key, value in updated_vars.items():
        if key not in existing_keys:
            new_lines.append(f"{key}={value}\n")
    
    # Escribir archivo
    with open(env_path, 'w') as f:
        f.writelines(new_lines)
    
    print(f"\n✅ Credenciales guardadas en {env_path}")
    print("\n📋 Checklist antes de reiniciar:")
    print(f"   ✅ API Key configurada")
    print(f"   ✅ API Secret configurada")
    print(f"   ✅ LIVE_TRADING=true")
    print(f"   ⚠️  IP {current_ip} debe estar en whitelist de Crypto.com Exchange")
    print()
    print("🔄 Siguiente paso: Reinicia el backend:")
    print("   docker compose restart backend")
    print()
    
    return True

def verify_connection():
    """Verificar conexión con Crypto.com Exchange"""
    print("\n" + "="*60)
    print("🔍 VERIFICANDO CONEXIÓN")
    print("="*60)
    print()
    
    try:
        from app.services.brokers.crypto_com_trade import trade_client
        
        print(f"📊 Estado del cliente:")
        print(f"   Live Trading: {trade_client.live_trading}")
        print(f"   Use Proxy: {trade_client.use_proxy}")
        print(f"   Base URL: {getattr(trade_client, 'base_url', 'N/A')}")
        print(f"   API Key configurada: {'Sí' if trade_client.api_key else 'No'}")
        print(f"   API Secret configurada: {'Sí' if trade_client.api_secret else 'No'}")
        print()
        
        if not trade_client.live_trading:
            print("⚠️  LIVE_TRADING está en false. Las órdenes serán simuladas (DRY RUN)")
            return False
        
        if not trade_client.api_key or not trade_client.api_secret:
            print("❌ Credenciales de API no configuradas")
            return False
        
        print("🔄 Probando conexión con Crypto.com Exchange...")
        
        # Intentar obtener el resumen de cuenta
        result = trade_client.get_account_summary()
        
        if result and "accounts" in result:
            print("✅ Conexión exitosa con Crypto.com Exchange!")
            print("\n💰 Balances:")
            for account in result.get("accounts", [])[:5]:
                currency = account.get("currency", "")
                balance = account.get("balance", "0")
                available = account.get("available", "0")
                print(f"   {currency}: {balance} (disponible: {available})")
            return True
        else:
            print("⚠️  Respuesta inesperada de la API")
            print(f"   Resultado: {result}")
            return False
            
    except Exception as e:
        print(f"❌ Error verificando conexión: {e}")
        print("\n💡 Posibles causas:")
        print("   - Credenciales incorrectas")
        print("   - IP no está en whitelist")
        print("   - API Key no tiene permisos de Trade")
        return False

def main():
    """Función principal"""
    print("\n" + "="*60)
    print("🚀 CONFIGURACIÓN DE LIVE TRADING - Crypto.com Exchange")
    print("="*60)
    print()
    
    # Verificar configuración actual
    env_vars = check_env_file()
    
    # Verificar si ya está configurado
    has_credentials = (
        env_vars.get('EXCHANGE_CUSTOM_API_KEY') and 
        env_vars.get('EXCHANGE_CUSTOM_API_KEY') != 'tu_api_key_aqui' and
        env_vars.get('EXCHANGE_CUSTOM_API_SECRET') and
        env_vars.get('EXCHANGE_CUSTOM_API_SECRET') != 'tu_api_secret_aqui'
    )
    
    if has_credentials and env_vars.get('LIVE_TRADING') == 'true':
        print("\n✅ Credenciales ya configuradas. Verificando conexión...")
        if verify_connection():
            print("\n🎉 ¡Todo listo! Las órdenes se ejecutarán en modo LIVE")
            return
    else:
        print("\n📝 Credenciales no configuradas o LIVE_TRADING=false")
        response = input("\n¿Deseas configurarlas ahora? (s/n): ").strip().lower()
        
        if response == 's':
            if interactive_setup():
                print("\n⚠️  IMPORTANTE: Reinicia el backend antes de usar órdenes reales:")
                print("   docker compose restart backend")
                print("\n🔄 Luego ejecuta este script de nuevo para verificar la conexión:")
                print("   docker compose exec backend python scripts/setup_live_trading.py")

if __name__ == "__main__":
    # Añadir el directorio backend al path
    backend_dir = Path(__file__).parent.parent
    sys.path.insert(0, str(backend_dir))
    
    main()

