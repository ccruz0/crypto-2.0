#!/usr/bin/env python3
"""
Diagnóstico detallado del problema de autenticación
Compara get_account_summary (falla) vs get_order_history (funciona)
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

def test_method(name, method, params, should_work=True):
    """Probar un método específico y mostrar detalles"""
    print(f"\n{'='*70}")
    print(f"🧪 Test: {name}")
    print(f"{'='*70}")
    
    client = CryptoComTradeClient()
    
    # Construir payload manualmente para ver exactamente qué se envía
    nonce_ms = int(time.time() * 1000)
    request_id = 1
    
    # Construir params_str igual que en sign_request
    if params:
        params_str = client._params_to_str(params, 0)
    else:
        params_str = json.dumps(params, separators=(',', ':'))  # "{}" when empty
    
    # String to sign
    string_to_sign = method + str(request_id) + client.api_key + params_str + str(nonce_ms)
    
    # Generar firma
    signature = hmac.new(
        client.api_secret.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Payload
    payload = {
        'id': request_id,
        'method': method,
        'api_key': client.api_key,
        'params': params,
        'nonce': nonce_ms,
        'sig': signature
    }
    
    print(f"📋 Detalles:")
    print(f"   Method: {method}")
    print(f"   ID: {request_id}")
    print(f"   Nonce: {nonce_ms}")
    print(f"   Params: {params}")
    print(f"   Params_str: {repr(params_str)}")
    print(f"   String to sign length: {len(string_to_sign)}")
    print(f"   String to sign (first 80 chars): {string_to_sign[:80]}...")
    print(f"   Signature (first 32 chars): {signature[:32]}...")
    
    # Hacer petición
    url = f"https://api.crypto.com/exchange/v1/{method}"
    print(f"\n🌐 Enviando a: {url}")
    
    try:
        response = requests.post(
            url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        print(f"📥 Respuesta:")
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                data = result.get('result', {}).get('data', result.get('result', {}).get('accounts', []))
                print(f"   ✅ ✅ ✅ SUCCESS! Code: {result.get('code')}")
                if isinstance(data, list):
                    print(f"   📊 Data: {len(data)} items")
                else:
                    print(f"   📊 Data: {type(data).__name__}")
                return True
            else:
                print(f"   ❌ Error code: {result.get('code')}")
                print(f"   Message: {result.get('message')}")
        elif response.status_code == 401:
            error = response.json()
            print(f"   ❌ 401 Error:")
            print(f"   Code: {error.get('code')}")
            print(f"   Message: {error.get('message')}")
        else:
            print(f"   ⚠️  Status {response.status_code}")
            try:
                print(f"   Response: {response.text[:200]}")
            except:
                pass
                
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    return False

def main():
    print("\n" + "="*70)
    print("🔍 DIAGNÓSTICO DETALLADO DE AUTENTICACIÓN")
    print("="*70)
    
    # Test 1: get_order_history (funciona)
    from datetime import datetime, timedelta
    end_time_ms = int(time.time() * 1000)
    start_time_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
    params_history = {
        'start_time': int(start_time_ms),
        'end_time': int(end_time_ms),
        'page_size': int(10),
        'page': int(0)
    }
    test_method("get_order_history (FUNCIONA)", "private/get-order-history", params_history, should_work=True)
    
    # Test 2: get_account_summary (falla)
    test_method("get_account_summary (FALLA)", "private/get-account-summary", {}, should_work=False)
    
    # Test 3: get_account_summary con params_str vacío (no "{}")
    print(f"\n{'='*70}")
    print("🧪 Test: get_account_summary con params_str = '' (cadena vacía)")
    print(f"{'='*70}")
    
    client = CryptoComTradeClient()
    method = "private/get-account-summary"
    params = {}
    nonce_ms = int(time.time() * 1000)
    request_id = 1
    
    # Probar con cadena vacía en lugar de "{}"
    params_str = ""  # Cadena vacía
    
    string_to_sign = method + str(request_id) + client.api_key + params_str + str(nonce_ms)
    signature = hmac.new(
        client.api_secret.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    payload = {
        'id': request_id,
        'method': method,
        'api_key': client.api_key,
        'params': params,
        'nonce': nonce_ms,
        'sig': signature
    }
    
    print(f"📋 Detalles:")
    print(f"   Params_str: {repr(params_str)} (cadena vacía)")
    print(f"   String to sign: {string_to_sign[:80]}...")
    
    url = f"https://api.crypto.com/exchange/v1/{method}"
    try:
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                print(f"   ✅ ✅ ✅ SUCCESS con params_str vacío!")
                return
        elif response.status_code == 401:
            error = response.json()
            print(f"   ❌ 401: {error.get('code')} - {error.get('message')}")
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    print(f"\n{'='*70}")
    print("📊 RESUMEN")
    print(f"{'='*70}")
    print("Comparando las diferencias entre métodos que funcionan y que fallan...")

if __name__ == "__main__":
    main()






