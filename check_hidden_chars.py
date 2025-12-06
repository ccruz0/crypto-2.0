#!/usr/bin/env python3
"""
Script para verificar caracteres ocultos en las credenciales
"""

import hmac
import hashlib
import time
import requests
import json
import os

def check_hidden_chars():
    print("🔍 INVESTIGACIÓN DE CARACTERES OCULTOS")
    print("=" * 45)
    
    API_KEY = os.getenv("CRYPTO_API_KEY", "").strip()
    SECRET_KEY = os.getenv("CRYPTO_API_SECRET", "").strip()
    
    print(f"\n1. Análisis detallado de API_KEY:")
    print(f"Raw: {repr(API_KEY)}")
    print(f"Length: {len(API_KEY)}")
    print(f"Bytes: {API_KEY.encode('utf-8')}")
    print(f"Characters: {[repr(c) for c in API_KEY]}")
    
    print(f"\n2. Análisis detallado de SECRET_KEY:")
    print(f"Raw: {repr(SECRET_KEY)}")
    print(f"Length: {len(SECRET_KEY)}")
    print(f"Bytes: {SECRET_KEY.encode('utf-8')}")
    print(f"Characters: {[repr(c) for c in SECRET_KEY]}")
    
    print(f"\n3. Verificando caracteres problemáticos:")
    problematic = [" ", "\t", "\n", "\r", ",", ".", "-", "_", "+", "=", "&", "|", "<", ">", "{", "}", "[", "]", "(", ")", "#", "@", "!", "$", "%", "^", "*", "~", "`", '"', "'", "\\", "/"]
    
    found_problems = False
    for char in problematic:
        if char in API_KEY:
            print(f"⚠️  API_KEY contiene: {repr(char)} en posición {API_KEY.find(char)}")
            found_problems = True
        if char in SECRET_KEY:
            print(f"⚠️  SECRET_KEY contiene: {repr(char)} en posición {SECRET_KEY.find(char)}")
            found_problems = True
    
    print(f"\n4. Verificando caracteres no imprimibles:")
    for i, char in enumerate(API_KEY):
        if ord(char) < 32 or ord(char) > 126:
            print(f"⚠️  API_KEY carácter no imprimible en posición {i}: {repr(char)} (ord: {ord(char)})")
            found_problems = True
    
    for i, char in enumerate(SECRET_KEY):
        if ord(char) < 32 or ord(char) > 126:
            print(f"⚠️  SECRET_KEY carácter no imprimible en posición {i}: {repr(char)} (ord: {ord(char)})")
            found_problems = True
    
    print(f"\n5. Verificando espacios al inicio/final:")
    print(f"API_KEY starts with space: {API_KEY.startswith(' ')}")
    print(f"API_KEY ends with space: {API_KEY.endswith(' ')}")
    print(f"SECRET_KEY starts with space: {SECRET_KEY.startswith(' ')}")
    print(f"SECRET_KEY ends with space: {SECRET_KEY.endswith(' ')}")
    
    # Probar con diferentes métodos de limpieza
    print(f"\n6. Probando diferentes métodos de limpieza:")
    clean_api_key = API_KEY.strip().replace(" ", "").replace("\t", "").replace("\n", "").replace("\r", "")
    clean_secret_key = SECRET_KEY.strip().replace(" ", "").replace("\t", "").replace("\n", "").replace("\r", "")
    
    print(f"API_KEY original: {repr(API_KEY)}")
    print(f"API_KEY limpio: {repr(clean_api_key)}")
    print(f"SECRET_KEY original: {repr(SECRET_KEY)}")
    print(f"SECRET_KEY limpio: {repr(clean_secret_key)}")
    
    if clean_api_key != API_KEY or clean_secret_key != SECRET_KEY:
        print("\n⚠️  DIFERENCIA DETECTADA! Probando con credenciales limpias...")
        
        # Probar con credenciales limpias
        nonce = int(time.time() * 1000)
        req_id = nonce
        METHOD = "private/get-account-summary"
        params = {}
        params_str = json.dumps(params, separators=(",", ":"))
        payload = f"{METHOD}{req_id}{clean_api_key}{nonce}{params_str}"
        signature = hmac.new(clean_secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        body = {"id": req_id, "method": METHOD, "api_key": clean_api_key, "sig": signature, "nonce": nonce, "params": params}
        
        try:
            r = requests.post(f"https://api.crypto.com/exchange/v1/{METHOD}", json=body, timeout=15)
            print(f"Con credenciales limpias: HTTP {r.status_code} - {r.text[:100]}")
            if r.status_code == 200:
                print("✅ ÉXITO con credenciales limpias!")
            else:
                print("❌ Aún falla con credenciales limpias")
        except Exception as e:
            print(f"Error con credenciales limpias: {e}")
    else:
        print("\n✅ No se detectaron caracteres problemáticos")
    
    if not found_problems:
        print("\n🔍 No se encontraron caracteres problemáticos obvios")
        print("El problema podría estar en otro lugar")

if __name__ == "__main__":
    check_hidden_chars()
