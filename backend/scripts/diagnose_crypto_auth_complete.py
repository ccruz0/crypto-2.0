#!/usr/bin/env python3
"""
Diagnóstico completo de autenticación Crypto.com
Prueba todos los formatos posibles para identificar cuál funciona
"""
import os
import sys
import json
import time
import hmac
import hashlib
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.crypto_com_guardrail import get_execution_context, SKIP_REASON
from app.services.brokers.crypto_com_trade import CryptoComTradeClient, _clean_env_secret

def test_format(name, method, req_id, nonce, api_key, api_secret, params, params_str_func):
    """Probar un formato específico de autenticación"""
    print(f"\n{'='*70}")
    print(f"🧪 Test: {name}")
    print(f"{'='*70}")
    
    # Construir params_str según la función proporcionada
    if params_str_func == "json_dumps":
        params_str = json.dumps(params, separators=(',', ':'))
    elif params_str_func == "empty_string":
        params_str = ""
    elif params_str_func == "params_to_str":
        from app.services.brokers.crypto_com_trade import CryptoComTradeClient
        client = CryptoComTradeClient()
        params_str = client._params_to_str(params, 0)
    else:
        params_str = ""
    
    # Construir string_to_sign según el formato
    if "nonce_before_params" in name:
        string_to_sign = f"{method}{req_id}{api_key}{nonce}{params_str}"
    else:  # params_before_nonce (default)
        string_to_sign = f"{method}{req_id}{api_key}{params_str}{nonce}"
    
    print(f"String to sign: {string_to_sign[:100]}...")
    print(f"Params_str: {repr(params_str)}")
    print(f"ID: {req_id}, Nonce: {nonce}, ID==Nonce: {req_id == nonce}")
    
    # Generar firma
    signature = hmac.new(
        api_secret.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Construir payload
    body = {
        'id': req_id,
        'method': method,
        'api_key': api_key,
        'sig': signature,
        'nonce': nonce,
        'params': params,
    }
    
    # Hacer petición
    url = 'https://api.crypto.com/exchange/v1/private/get-account-summary'
    try:
        response = requests.post(url, json=body, headers={'Content-Type': 'application/json'}, timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                accounts = result.get('result', {}).get('accounts', [])
                print(f"✅ ✅ ✅ SUCCESS! Found {len(accounts)} accounts!")
                print(f"✅ ✅ ✅ FORMATO CORRECTO: {name}")
                return True
            else:
                print(f"❌ Error code: {result.get('code')}, message: {result.get('message')}")
        else:
            error = response.json()
            print(f"❌ Status {response.status_code}: {error.get('code')} - {error.get('message')}")
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    return False

def main():
    if get_execution_context() != "AWS":
        print(SKIP_REASON)
        sys.exit(0)
    print("\n" + "="*70)
    print("🔍 DIAGNÓSTICO COMPLETO DE AUTENTICACIÓN CRYPTO.COM")
    print("="*70)
    
    # Cargar credenciales
    api_key_raw = os.getenv('EXCHANGE_CUSTOM_API_KEY', '')
    api_secret_raw = os.getenv('EXCHANGE_CUSTOM_API_SECRET', '')
    
    api_key = _clean_env_secret(api_key_raw)
    api_secret = _clean_env_secret(api_secret_raw)
    
    if not api_key or not api_secret:
        print("❌ Credenciales no configuradas")
        return
    
    print(f"\n📋 Credenciales:")
    print(f"   API Key: {api_key[:10]}...{api_key[-4:]}")
    print(f"   API Secret: {'✅ Configurado' if api_secret else '❌ No configurado'}")
    
    method = 'private/get-account-summary'
    params = {}
    nonce = int(time.time() * 1000)
    
    # Probar todos los formatos posibles
    formats_to_test = [
        # Formato 1: id=1, nonce antes de params, json.dumps para params vacíos
        ("id=1, nonce_before_params, json_dumps", 1, nonce, "json_dumps", "nonce_before_params"),
        
        # Formato 2: id=1, params antes de nonce, json.dumps para params vacíos
        ("id=1, params_before_nonce, json_dumps", 1, nonce, "json_dumps", "params_before_nonce"),
        
        # Formato 3: id=nonce, nonce antes de params, json.dumps para params vacíos
        ("id=nonce, nonce_before_params, json_dumps", nonce, nonce, "json_dumps", "nonce_before_params"),
        
        # Formato 4: id=nonce, params antes de nonce, json.dumps para params vacíos
        ("id=nonce, params_before_nonce, json_dumps", nonce, nonce, "json_dumps", "params_before_nonce"),
        
        # Formato 5: id=1, nonce antes de params, string vacío para params vacíos
        ("id=1, nonce_before_params, empty_string", 1, nonce, "empty_string", "nonce_before_params"),
        
        # Formato 6: id=1, params antes de nonce, string vacío para params vacíos
        ("id=1, params_before_nonce, empty_string", 1, nonce, "empty_string", "params_before_nonce"),
    ]
    
    for name, req_id, nonce_val, params_str_type, order in formats_to_test:
        full_name = f"{name}"
        success = test_format(full_name, method, req_id, nonce_val, api_key, api_secret, params, params_str_type)
        if success:
            print(f"\n🎉 🎉 🎉 FORMATO CORRECTO ENCONTRADO: {full_name} 🎉 🎉 🎉")
            return
    
    print(f"\n❌ Ninguno de los formatos probados funcionó")
    print(f"💡 El problema puede estar en:")
    print(f"   1. IP no whitelisted en Crypto.com")
    print(f"   2. API Key sin permisos de 'Read'")
    print(f"   3. API Key deshabilitada o revocada")
    print(f"   4. Credenciales incorrectas")

if __name__ == "__main__":
    main()







