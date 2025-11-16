#!/usr/bin/env python3
"""
Script para verificar conexión y firma correcta con Crypto.com **Exchange API v1**
Verifica firma correcta para Exchange API v1 y ayuda a diagnosticar errores 40101 sin exponer secretos
"""

import hmac
import hashlib
import time
import requests
import json
import os


def demo_crypto_com_error():
    print("=" * 80)
    print("🔍 DEMOSTRACIÓN DE CONEXIÓN CORRECTA (Exchange API v1)")
    print("=" * 80)
    print()

    # ⚠️ No hardcodes: usar variables de entorno
    #   export CRYPTO_API_KEY="..."
    #   export CRYPTO_API_SECRET="..."
    API_KEY = (os.getenv("CRYPTO_API_KEY") or "").strip()
    SECRET_KEY = (os.getenv("CRYPTO_API_SECRET") or "").strip()

    # Validaciones con asserts
    assert API_KEY and SECRET_KEY, "Faltan claves"
    assert "\n" not in API_KEY+SECRET_KEY, "Claves contienen saltos de línea"
    
    print(f"✅ API_KEY: {len(API_KEY)} chars, SECRET_KEY: {len(SECRET_KEY)} chars")

    BASE = "https://api.crypto.com/exchange/v1"
    METHOD = "private/get-account-summary"

    # Firma para Exchange API v1:
    # payload = METHOD + id + api_key + nonce + params_json (sin espacios)
    nonce = int(time.time() * 1000)
    req_id = nonce
    params = {}
    params_str = json.dumps(params, separators=(",", ":"))  # "{}" cuando está vacío
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

    print("📤 BODY ENVIADO:")
    safe_body = dict(body)
    safe_body["api_key"] = API_KEY[:4] + "…" + API_KEY[-4:]
    print(json.dumps(safe_body, indent=2))
    
    # Debug info adicional
    print(f"\n🔍 DEBUG INFO:")
    print(f"   API_KEY repr: {repr(API_KEY[:10])}...")
    print(f"   SECRET_KEY repr: {repr(SECRET_KEY[:10])}...")
    print(f"   Payload: {repr(payload[:50])}...")
    print(f"   Signature: {signature[:20]}...")

    try:
        r = requests.post(f"{BASE}/{METHOD}", json=body, timeout=15)
        print(f"\n📡 HTTP: {r.status_code}")
        print("📄 RESPUESTA (primeros 400 chars):\n", r.text[:400])
        
        if r.status_code == 200:
            try:
                result = r.json()
                if "result" in result:
                    print("✅ ÉXITO: Respuesta contiene 'result'")
                else:
                    print("⚠️  Respuesta HTTP 200 pero sin 'result'")
            except:
                print("⚠️  Respuesta HTTP 200 pero no es JSON válido")
        elif r.status_code == 40101:
            print("❌ ERROR 40101: Authentication failure - verificar API_KEY/SECRET")
        else:
            print(f"❌ ERROR HTTP {r.status_code}")
            
    except Exception as e:
        print(f"❌ EXCEPCIÓN: {e}")


if __name__ == "__main__":
    demo_crypto_com_error()
