#!/usr/bin/env python3
"""
Script de diagnóstico para verificar la autenticación de Crypto.com en AWS
"""
import os
import sys
import requests
import time
import hmac
import hashlib
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.brokers.crypto_com_trade import CryptoComTradeClient
from app.core.config import settings

def _preview_secret(value: str, left: int = 4, right: int = 4) -> str:
    v = value or ""
    if not v:
        return "<NOT_SET>"
    if len(v) <= left + right:
        return "<SET>"
    return f"{v[:left]}....{v[-right:]}"

def check_credentials():
    """Verificar configuración de credenciales"""
    print("\n" + "="*70)
    print("🔍 DIAGNÓSTICO DE AUTENTICACIÓN CRYPTO.COM")
    print("="*70 + "\n")
    
    # Check environment variables
    api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "")
    api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "")
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    proxy_url = os.getenv("CRYPTO_PROXY_URL", "http://127.0.0.1:9000")
    base_url = os.getenv("EXCHANGE_CUSTOM_BASE_URL", "https://api.crypto.com/exchange/v1")
    
    print("📋 **Configuración Actual:**")
    print(f"  • USE_CRYPTO_PROXY: {use_proxy}")
    print(f"  • API Key: {_preview_secret(api_key)} (len: {len(api_key)})")
    print(f"  • API Secret: {'✅ Configurado' if api_secret else '❌ No configurado'} (len: {len(api_secret)})")
    print(f"  • Base URL: {base_url}")
    if use_proxy:
        print(f"  • Proxy URL: {proxy_url}")
    print()
    
    # Check IP
    try:
        egress_ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
        print(f"🌐 **IP del Servidor:** {egress_ip}")
        print(f"  ⚠️  Esta IP debe estar en la whitelist de Crypto.com")
    except Exception as e:
        print(f"  ❌ No se pudo obtener la IP: {e}")
    print()
    
    # Check credentials format
    issues = []
    if not api_key:
        issues.append("❌ EXCHANGE_CUSTOM_API_KEY no está configurada")
    elif len(api_key) < 10:
        issues.append(f"⚠️  API Key parece muy corta (len: {len(api_key)})")
    
    if not api_secret:
        issues.append("❌ EXCHANGE_CUSTOM_API_SECRET no está configurada")
    elif len(api_secret) < 10:
        issues.append(f"⚠️  API Secret parece muy corta (len: {len(api_secret)})")
    
    # Check for common issues
    if api_key and api_secret:
        # Check for whitespace
        if api_key != api_key.strip():
            issues.append("⚠️  API Key tiene espacios al inicio/final")
        if api_secret != api_secret.strip():
            issues.append("⚠️  API Secret tiene espacios al inicio/final")
        
        # Check for quotes
        if (api_key.startswith('"') and api_key.endswith('"')) or (api_key.startswith("'") and api_key.endswith("'")):
            issues.append("⚠️  API Key está envuelta en comillas (debería estar sin comillas)")
        if (api_secret.startswith('"') and api_secret.endswith('"')) or (api_secret.startswith("'") and api_secret.endswith("'")):
            issues.append("⚠️  API Secret está envuelta en comillas (debería estar sin comillas)")
    
    if issues:
        print("⚠️  **Problemas Detectados:**")
        for issue in issues:
            print(f"  {issue}")
        print()
    
    # Test API connection
    print("🧪 **Prueba de Conexión:**")
    print()
    
    client = CryptoComTradeClient()
    
    # Test 1: Public endpoint (no auth needed)
    print("1️⃣ Probando endpoint público (sin autenticación)...")
    try:
        response = requests.get(
            'https://api.crypto.com/v2/public/get-ticker?instrument_name=BTC_USDT',
            timeout=5,
        )
        if response.status_code == 200:
            print("   ✅ Conexión a Crypto.com funciona correctamente")
        else:
            print(f"   ❌ Error de conexión: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    print()
    
    # Test 2: Private endpoint with current credentials
    print("2️⃣ Probando autenticación con credenciales actuales...")
    try:
        result = client.get_account_summary()
        if result and 'accounts' in result:
            print(f"   ✅ Autenticación exitosa! Encontradas {len(result.get('accounts', []))} cuentas")
        elif result and 'error' in result:
            print(f"   ❌ Error de autenticación: {result.get('error')}")
        else:
            print(f"   ⚠️  Respuesta inesperada: {list(result.keys())[:5] if result else 'None'}")
    except ValueError as e:
        print(f"   ❌ Error de configuración: {e}")
    except RuntimeError as e:
        error_msg = str(e)
        if "40101" in error_msg:
            print(f"   ❌ Error 40101: Autenticación fallida")
            print(f"   📋 Posibles causas:")
            print(f"      • API Key o Secret incorrectos")
            print(f"      • API Key no tiene permisos de 'Read'")
            print(f"      • API Key está deshabilitada o suspendida")
            print(f"      • IP {egress_ip} no está en la whitelist")
        elif "40103" in error_msg:
            print(f"   ❌ Error 40103: IP no permitida")
            print(f"   📋 Solución:")
            print(f"      • Agregar IP {egress_ip} a la whitelist en Crypto.com Exchange")
        else:
            print(f"   ❌ Error: {error_msg}")
    except Exception as e:
        print(f"   ❌ Error inesperado: {e}")
    print()
    
    # Test 3: Verify signature generation
    if api_key and api_secret:
        print("3️⃣ Verificando generación de firma...")
        try:
            method = "private/get-account-summary"
            params = {}
            nonce_ms = int(time.time() * 1000)
            
            # Build params string (empty for this method)
            params_str = ""
            
            # String to sign
            string_to_sign = f"{method}1{api_key}{params_str}{nonce_ms}"
            
            # Generate signature
            signature = hmac.new(
                api_secret.encode('utf-8'),
                string_to_sign.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            print(f"   ✅ Firma generada correctamente")
            print(f"   📋 Detalles:")
            print(f"      • Method: {method}")
            print(f"      • API Key: {_preview_secret(api_key)}")
            print(f"      • Nonce: {nonce_ms}")
            print(f"      • String to sign length: {len(string_to_sign)}")
            print(f"      • Signature: {signature[:16]}...{signature[-8:]}")
        except Exception as e:
            print(f"   ❌ Error generando firma: {e}")
        print()
    
    # Recommendations
    print("💡 **Recomendaciones:**")
    if not api_key or not api_secret:
        print("   1. Configurar EXCHANGE_CUSTOM_API_KEY y EXCHANGE_CUSTOM_API_SECRET")
    else:
        print("   1. Verificar en Crypto.com Exchange:")
        print("      • Settings → API Keys → Editar tu API Key")
        print("      • Verificar que tenga permisos de 'Read'")
        print("      • Verificar que esté activa (no deshabilitada)")
        print(f"   2. Agregar IP a whitelist: {egress_ip}")
        print("   3. Si el problema persiste, regenerar la API Key")
    
    print()
    print("="*70 + "\n")

if __name__ == "__main__":
    check_credentials()







