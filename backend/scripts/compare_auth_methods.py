#!/usr/bin/env python3
"""
Comparar exactamente qué se envía en get_order_history (funciona) vs get_account_summary (falla)
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

def test_and_show_details(name, method, params):
    """Probar un método y mostrar todos los detalles"""
    print(f"\n{'='*70}")
    print(f"🧪 {name}")
    print(f"{'='*70}")
    
    client = CryptoComTradeClient()
    
    # Construir exactamente como lo hace sign_request
    nonce_ms = int(time.time() * 1000)
    request_id = 1
    
    # Construir params_str
    if params:
        params_str = client._params_to_str(params, 0)
    else:
        params_str = ""  # Cambio reciente: cadena vacía
    
    # String to sign
    string_to_sign = method + str(request_id) + client.api_key + params_str + str(nonce_ms)
    
    # Firma
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
    
    print(f"📋 Detalles completos:")
    print(f"   Method: {method}")
    print(f"   ID: {request_id}")
    print(f"   Nonce: {nonce_ms}")
    print(f"   Params: {params}")
    print(f"   Params_str: {repr(params_str)} (len: {len(params_str)})")
    print(f"   String to sign: {string_to_sign}")
    print(f"   String to sign length: {len(string_to_sign)}")
    print(f"   Signature: {signature[:32]}...{signature[-16:]}")
    print(f"   Payload keys: {list(payload.keys())}")
    
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
                print(f"   ✅ ✅ ✅ SUCCESS!")
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
        import traceback
        traceback.print_exc()
    
    return False

def main():
    print("\n" + "="*70)
    print("🔍 COMPARACIÓN DETALLADA: get_order_history vs get_account_summary")
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
    works = test_and_show_details("get_order_history (FUNCIONA)", "private/get-order-history", params_history)
    
    # Test 2: get_account_summary (falla)
    fails = test_and_show_details("get_account_summary (FALLA)", "private/get-account-summary", {})
    
    # Comparar diferencias
    print(f"\n{'='*70}")
    print("📊 ANÁLISIS DE DIFERENCIAS")
    print(f"{'='*70}")
    print(f"get_order_history funciona: {works}")
    print(f"get_account_summary funciona: {fails}")
    
    if works and not fails:
        print("\n💡 DIFERENCIA CLAVE:")
        print("   • get_order_history tiene params con valores")
        print("   • get_account_summary tiene params vacío {}")
        print("   • Ambos usan el mismo formato de string_to_sign")
        print("   • El problema puede estar en cómo Crypto.com valida params vacíos")

if __name__ == "__main__":
    main()






