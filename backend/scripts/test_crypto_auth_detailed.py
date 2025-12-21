#!/usr/bin/env python3
"""
Diagnóstico detallado de autenticación Crypto.com
Muestra exactamente qué se envía y compara con diferentes formatos
"""
import os
import sys
import json
import time
import hmac
import hashlib
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.brokers.crypto_com_trade import CryptoComTradeClient, _clean_env_secret

def test_auth():
    """Probar autenticación con diagnóstico detallado"""
    print("\n" + "="*70)
    print("🔍 DIAGNÓSTICO DETALLADO DE AUTENTICACIÓN")
    print("="*70 + "\n")
    
    # Cargar credenciales
    api_key_raw = os.getenv('EXCHANGE_CUSTOM_API_KEY', '')
    api_secret_raw = os.getenv('EXCHANGE_CUSTOM_API_SECRET', '')
    
    api_key = _clean_env_secret(api_key_raw)
    api_secret = _clean_env_secret(api_secret_raw)
    
    print(f"📋 Credenciales:")
    print(f"   API Key: {api_key[:10]}...{api_key[-4:]}")
    print(f"   API Secret: {'✅ Configurado' if api_secret else '❌ No configurado'}")
    print()
    
    if not api_key or not api_secret:
        print("❌ Credenciales no configuradas")
        return
    
    method = 'private/get-account-summary'
    params = {}
    nonce_ms = int(time.time() * 1000)
    request_id = 1
    
    # Probar con el formato actual del código
    print("🧪 Probando formato actual del código:")
    print(f"   • Method: {method}")
    print(f"   • ID: {request_id}")
    print(f"   • Nonce: {nonce_ms}")
    print(f"   • Params: {params}")
    print()
    
    # Construir params_str (cadena vacía para params vacíos)
    params_str = ""
    
    # String to sign: method + id + api_key + params_str + nonce
    string_to_sign = method + str(request_id) + api_key + params_str + str(nonce_ms)
    
    print(f"📝 String to sign:")
    print(f"   {string_to_sign}")
    print(f"   Longitud: {len(string_to_sign)}")
    print()
    
    # Generar firma
    signature = hmac.new(
        api_secret.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    print(f"🔐 Firma generada:")
    print(f"   {signature[:32]}...{signature[-16:]}")
    print()
    
    # Construir payload
    payload = {
        'id': request_id,
        'method': method,
        'api_key': api_key,
        'params': params,
        'nonce': nonce_ms,
        'sig': signature
    }
    
    print(f"📤 Payload a enviar:")
    print(f"   {json.dumps(payload, indent=2)}")
    print()
    
    # Hacer petición
    url = 'https://api.crypto.com/exchange/v1/private/get-account-summary'
    print(f"🌐 Enviando petición a: {url}")
    print()
    
    try:
        response = requests.post(
            url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        print(f"📥 Respuesta:")
        print(f"   Status Code: {response.status_code}")
        print(f"   Headers: {dict(response.headers)}")
        print()
        
        if response.status_code == 200:
            result = response.json()
            print(f"   JSON Response:")
            print(f"   {json.dumps(result, indent=2)}")
            print()
            
            if result.get('code') == 0:
                accounts = result.get('result', {}).get('accounts', [])
                print(f"✅ ✅ ✅ SUCCESS! Found {len(accounts)} accounts!")
                return True
            else:
                print(f"❌ Error code: {result.get('code')}")
                print(f"   Message: {result.get('message')}")
                print(f"   Data: {result.get('data')}")
        else:
            try:
                error = response.json()
                print(f"❌ Error {response.status_code}:")
                print(f"   {json.dumps(error, indent=2)}")
            except:
                print(f"❌ Error {response.status_code}: {response.text[:200]}")
                
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
    
    return False

if __name__ == "__main__":
    test_auth()






