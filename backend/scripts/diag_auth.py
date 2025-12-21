#!/usr/bin/env python3
import os
import sys
import requests
import time
import hmac
import hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Get IP
egress_ip = requests.get('https://api.ipify.org', timeout=5).text.strip()
print(f'IP del Servidor: {egress_ip}')
print()

# Get credentials
api_key = os.getenv('EXCHANGE_CUSTOM_API_KEY', '').strip()
api_secret = os.getenv('EXCHANGE_CUSTOM_API_SECRET', '').strip()

print('Credenciales:')
print(f'  API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else ""} (len: {len(api_key)})')
print(f'  API Secret: {"Configurado" if api_secret else "No configurado"} (len: {len(api_secret)})')
print()

if not api_key or not api_secret:
    print('ERROR: Credenciales no configuradas')
    sys.exit(1)

# Test signature
method = 'private/get-account-summary'
request_id = 1
nonce_ms = int(time.time() * 1000)
params_str = ''
string_to_sign = f'{method}{request_id}{api_key}{params_str}{nonce_ms}'
signature = hmac.new(api_secret.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

print('Firma generada:')
print(f'  String to sign length: {len(string_to_sign)}')
print()

# Make request
payload = {
    'id': request_id,
    'method': method,
    'api_key': api_key,
    'params': {},
    'nonce': nonce_ms,
    'sig': signature
}

url = f'https://api.crypto.com/exchange/v1/{method}'
response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)

print(f'Respuesta: Status {response.status_code}')
if response.status_code == 401:
    error_data = response.json()
    print(f'  Error {error_data.get("code")}: {error_data.get("message")}')
    print()
    print('Causas posibles:')
    print(f'  1. IP {egress_ip} no esta en la whitelist')
    print('  2. API Key no tiene permisos de Read')
    print('  3. API Key esta deshabilitada')
    print('  4. Credenciales incorrectas')
elif response.status_code == 200:
    result = response.json()
    if result.get('code') == 0:
        print('  Autenticacion exitosa!')
    else:
        print(f'  Codigo: {result.get("code")}')







