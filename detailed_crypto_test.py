#!/usr/bin/env python3
"""
Script detallado para diagnosticar problemas con Crypto.com Exchange API
"""

import hmac
import hashlib
import time
import requests
import json
import os

def detailed_crypto_test():
    print("=" * 80)
    print("🔍 DIAGNÓSTICO DETALLADO - Crypto.com Exchange API")
    print("=" * 80)
    
    # Obtener credenciales
    API_KEY = (os.getenv("CRYPTO_API_KEY") or "").strip()
    SECRET_KEY = (os.getenv("CRYPTO_API_SECRET") or "").strip()
    
    print(f"✅ API_KEY: {len(API_KEY)} chars")
    print(f"✅ SECRET_KEY: {len(SECRET_KEY)} chars")
    print(f"✅ IP del servidor: {requests.get('https://ifconfig.me').text.strip()}")
    
    # Probar endpoint público primero
    print("\n🌐 Probando endpoint público...")
    try:
        public_response = requests.get("https://api.crypto.com/exchange/v1/public/get-instruments", timeout=10)
        print(f"   Público HTTP: {public_response.status_code}")
        if public_response.status_code == 200:
            print("   ✅ Endpoint público funciona")
        else:
            print("   ❌ Problema con endpoint público")
    except Exception as e:
        print(f"   ❌ Error en endpoint público: {e}")
    
    # Probar autenticación
    print("\n🔐 Probando autenticación...")
    BASE = "https://api.crypto.com/exchange/v1"
    METHOD = "private/get-account-summary"
    
    nonce = int(time.time() * 1000)
    req_id = nonce
    params = {}
    params_str = json.dumps(params, separators=(",", ":"))
    payload = f"{METHOD}{req_id}{API_KEY}{nonce}{params_str}"
    
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    
    body = {
        "id": req_id,
        "method": METHOD,
        "api_key": API_KEY,
        "sig": signature,
        "nonce": nonce,
        "params": params,
    }
    
    print(f"   Payload: {payload[:50]}...")
    print(f"   Signature: {signature[:20]}...")
    
    try:
        r = requests.post(f"{BASE}/{METHOD}", json=body, timeout=15)
        print(f"   HTTP: {r.status_code}")
        print(f"   Response: {r.text[:300]}")
        
        if r.status_code == 200:
            print("   ✅ AUTENTICACIÓN EXITOSA!")
        elif r.status_code == 401:
            print("   ❌ Error 401: Verificar credenciales y IP whitelist")
        else:
            print(f"   ❌ Error HTTP {r.status_code}")
            
    except Exception as e:
        print(f"   ❌ Excepción: {e}")

if __name__ == "__main__":
    detailed_crypto_test()
