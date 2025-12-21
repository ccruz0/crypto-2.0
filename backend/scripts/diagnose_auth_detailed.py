#!/usr/bin/env python3
"""
Diagnóstico detallado de autenticación Crypto.com
"""
import os
import sys
import requests
import time
import hmac
import hashlib
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _preview_secret(value: str, left: int = 4, right: int = 4) -> str:
    v = value or ""
    if not v:
        return "<NOT_SET>"
    if len(v) <= left + right:
        return "<SET>"
    return f"{v[:left]}....{v[-right:]}"

print("\n" + "="*70)
print("🔍 DIAGNÓSTICO DETALLADO DE AUTENTICACIÓN")
print("="*70 + "\n")

# Get IP
try:
    egress_ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
    print(f"🌐 IP del Servidor: {egress_ip}")
    print(f"   ⚠️  Esta IP DEBE estar en la whitelist de Crypto.com Exchange")
except Exception as e:
    print(f"   ❌ No se pudo obtener IP: {e}")
    egress_ip = "unknown"

print()

# Get credentials
api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "").strip()
api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "").strip()

print("📋 Credenciales:")
print(f"   • API Key: {_preview_secret(api_key)} (len: {len(api_key)})")
print(f"   • API Secret: {'✅ Configurado' if api_secret else '❌ No configurado'} (len: {len(api_secret)})")
print()

if not api_key or not api_secret:
    print("❌ Credenciales no configuradas. No se puede continuar.")
    sys.exit(1)

# Test signature generation
print("🔐 Probando Generación de Firma:")
method = "private/get-account-summary"
params = {}
request_id = 1
nonce_ms = int(time.time() * 1000)

# Build params string (empty for this method)
params_str = ""

# String to sign: method + id + api_key + params_str + nonce
string_to_sign = f"{method}{request_id}{api_key}{params_str}{nonce_ms}"

# Generate signature
signature = hmac.new(
    api_secret.encode('utf-8'),
    string_to_sign.encode('utf-8'),
    hashlib.sha256
).hexdigest()

print(f"   • Method: {method}")
print(f"   • Request ID: {request_id}")
print(f"   • Nonce: {nonce_ms}")
print(f"   • String to sign length: {len(string_to_sign)}")
print(f"   • Signature: {signature[:20]}...{signature[-10:]}")
print()

# Build payload
payload = {
    "id": request_id,
    "method": method,
    "api_key": api_key,
    "params": params,
    "nonce": nonce_ms,
    "sig": signature
}

print("📤 Payload a enviar:")
print(f"   • URL: https://api.crypto.com/exchange/v1/{method}")
print(f"   • Method: POST")
print(f"   • Headers: Content-Type: application/json")
print(f"   • Payload keys: {list(payload.keys())}")
print()

# Make request
print("🌐 Enviando solicitud...")
try:
    url = f"https://api.crypto.com/exchange/v1/{method}"
    response = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=10
    )
    
    print(f"   • Status Code: {response.status_code}")
    
    if response.status_code == 401:
        error_data = response.json()
        error_code = error_data.get("code", 0)
        error_msg = error_data.get("message", "")
        
        print(f"   ❌ Error {error_code}: {error_msg}")
        print()
        print("🔍 Análisis del Error 40101:")
        print("   Este error puede ser causado por:")
        print("   1. IP no whitelisted:")
        print(f"      → Agregar IP {egress_ip} en Crypto.com Exchange")
        print("      → Settings → API Keys → Editar API Key → IP Whitelist")
        print()
        print("   2. API Key sin permisos:")
        print("      → Verificar que la API Key tenga permiso 'Read'")
        print("      → Settings → API Keys → Editar API Key → Permissions")
        print()
        print("   3. API Key deshabilitada:")
        print("      → Verificar que la API Key esté activa")
        print("      → Settings → API Keys → Estado de la API Key")
        print()
        print("   4. Credenciales incorrectas:")
        print("      → Verificar que EXCHANGE_CUSTOM_API_KEY sea correcta")
        print("      → Verificar que EXCHANGE_CUSTOM_API_SECRET sea correcta")
        print("      → Si es necesario, regenerar la API Key en Crypto.com")
        print()
    elif response.status_code == 200:
        result = response.json()
        if result.get("code") == 0:
            print("   ✅ Autenticación exitosa!")
            if "result" in result and "accounts" in result["result"]:
                accounts = result["result"]["accounts"]
                print(f"   📊 Encontradas {len(accounts)} cuentas")
        else:
            print(f"   ⚠️  Respuesta: {result}")
    else:
        print(f"   ⚠️  Status inesperado: {response.status_code}")
        print(f"   Respuesta: {response.text[:200]}")
        
except Exception as e:
    print(f"   ❌ Error: {e}")

print()
print("="*70 + "\n")







