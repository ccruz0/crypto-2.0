#!/usr/bin/env python3
"""
Servidor para obtener datos reales de trading de Crypto.com
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import json
import hmac
import hashlib
import time
import base64
from datetime import datetime
import logging

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración de API de Crypto.com
# NOTA: Necesitas reemplazar estos valores con tus credenciales reales
API_KEY = "tu_api_key_aqui"  # Reemplaza con tu API key real
SECRET_KEY = "tu_secret_key_aqui"  # Reemplaza con tu secret key real
BASE_URL = "https://api.crypto.com/v2"

def generate_signature(method, path, params, secret_key):
    """Generar firma para autenticación con Crypto.com API"""
    timestamp = str(int(time.time() * 1000))
    nonce = str(int(time.time() * 1000))
    
    # Crear string para firmar
    sign_string = f"{method}{path}{timestamp}{nonce}"
    if params:
        sign_string += json.dumps(params, separators=(',', ':'))
    
    # Generar firma HMAC
    signature = hmac.new(
        secret_key.encode('utf-8'),
        sign_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return signature, timestamp, nonce

def make_authenticated_request(method, endpoint, params=None):
    """Hacer petición autenticada a Crypto.com API"""
    try:
        path = f"/v2{endpoint}"
        signature, timestamp, nonce = generate_signature(method, path, params, SECRET_KEY)
        
        headers = {
            'Content-Type': 'application/json',
            'X-MBX-APIKEY': API_KEY,
            'X-MBX-SIGNATURE': signature,
            'X-MBX-TIMESTAMP': timestamp,
            'X-MBX-NONCE': nonce
        }
        
        url = f"{BASE_URL}{endpoint}"
        
        if method == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=10)
        elif method == 'POST':
            response = requests.post(url, headers=headers, json=params, timeout=10)
        
        response.raise_for_status()
        return response.json()
        
    except Exception as e:
        logger.error(f"Error en petición autenticada: {e}")
        return None

@app.route('/api/account/balance')
def get_real_balance():
    """Obtener balance real de la cuenta"""
    try:
        # Intentar obtener balance real
        balance_data = make_authenticated_request('GET', '/private/get-account-summary')
        
        if balance_data and 'result' in balance_data:
            accounts = balance_data['result'].get('accounts', [])
            
            # Calcular total en USD
            total_usd = 0
            crypto_balance = {}
            account_list = []
            
            for account in accounts:
                currency = account.get('currency', '')
                balance = float(account.get('balance', 0))
                available = float(account.get('available', 0))
                frozen = float(account.get('frozen', 0))
                
                if balance > 0:
                    crypto_balance[currency] = balance
                    account_list.append({
                        'currency': currency,
                        'balance': balance,
                        'available': available,
                        'frozen': frozen
                    })
            
            return jsonify({
                'total_usd': total_usd,
                'available_usd': total_usd,
                'crypto_balance': crypto_balance,
                'accounts': account_list,
                'source': 'Crypto.com API (Real)'
            })
        else:
            # Fallback a datos mock si no hay credenciales reales
            logger.warning("Usando datos mock - configura credenciales reales para obtener datos reales")
            return jsonify({
                "total_usd": 50000.0,
                "available_usd": 25000.0,
                "crypto_balance": {
                    "BTC": 0.5,
                    "ETH": 2.0,
                    "USDT": 1000.0
                },
                "accounts": [
                    {
                        "currency": "BTC",
                        "balance": 0.5,
                        "available": 0.5,
                        "frozen": 0.0
                    },
                    {
                        "currency": "ETH", 
                        "balance": 2.0,
                        "available": 2.0,
                        "frozen": 0.0
                    },
                    {
                        "currency": "USDT",
                        "balance": 1000.0,
                        "available": 1000.0,
                        "frozen": 0.0
                    }
                ],
                "source": "Mock Data (Configure real API credentials)"
            })
            
    except Exception as e:
        logger.error(f"Error obteniendo balance: {e}")
        return jsonify({
            "error": str(e),
            "source": "Error"
        }), 500

@app.route('/api/orders/open')
def get_real_open_orders():
    """Obtener órdenes abiertas reales"""
    try:
        # Intentar obtener órdenes abiertas reales
        orders_data = make_authenticated_request('GET', '/private/get-open-orders')
        
        if orders_data and 'result' in orders_data:
            orders = orders_data['result'].get('orders', [])
            
            # Convertir formato de Crypto.com a formato esperado por el frontend
            formatted_orders = []
            for order in orders:
                formatted_orders.append({
                    'order_id': order.get('order_id', ''),
                    'client_oid': order.get('client_oid', ''),
                    'status': order.get('status', ''),
                    'side': order.get('side', ''),
                    'order_type': order.get('order_type', ''),
                    'instrument_name': order.get('instrument_name', ''),
                    'quantity': str(order.get('quantity', 0)),
                    'limit_price': str(order.get('limit_price', 0)) if order.get('limit_price') else None,
                    'order_value': str(order.get('order_value', 0)) if order.get('order_value') else None,
                    'create_time': int(order.get('create_time', 0)),
                    'update_time': int(order.get('update_time', 0))
                })
            
            return jsonify({
                'orders': formatted_orders,
                'source': 'Crypto.com API (Real)'
            })
        else:
            # Fallback a datos mock
            logger.warning("Usando datos mock para órdenes abiertas")
            return jsonify({
                'orders': [],
                'source': 'Mock Data (Configure real API credentials)'
            })
            
    except Exception as e:
        logger.error(f"Error obteniendo órdenes abiertas: {e}")
        return jsonify({
            'orders': [],
            'error': str(e),
            'source': 'Error'
        })

@app.route('/api/orders/history')
def get_real_order_history():
    """Obtener historial de órdenes reales"""
    try:
        # Intentar obtener historial de órdenes reales
        history_data = make_authenticated_request('GET', '/private/get-order-history')
        
        if history_data and 'result' in history_data:
            orders = history_data['result'].get('orders', [])
            
            # Convertir formato de Crypto.com a formato esperado por el frontend
            formatted_orders = []
            for order in orders:
                formatted_orders.append({
                    'order_id': order.get('order_id', ''),
                    'client_oid': order.get('client_oid', ''),
                    'status': order.get('status', ''),
                    'side': order.get('side', ''),
                    'order_type': order.get('order_type', ''),
                    'instrument_name': order.get('instrument_name', ''),
                    'quantity': str(order.get('quantity', 0)),
                    'limit_price': str(order.get('limit_price', 0)) if order.get('limit_price') else None,
                    'order_value': str(order.get('order_value', 0)) if order.get('order_value') else None,
                    'create_time': int(order.get('create_time', 0)),
                    'update_time': int(order.get('update_time', 0))
                })
            
            return jsonify({
                'orders': formatted_orders,
                'source': 'Crypto.com API (Real)'
            })
        else:
            # Fallback a datos mock
            logger.warning("Usando datos mock para historial de órdenes")
            return jsonify({
                'orders': [],
                'source': 'Mock Data (Configure real API credentials)'
            })
            
    except Exception as e:
        logger.error(f"Error obteniendo historial de órdenes: {e}")
        return jsonify({
            'orders': [],
            'error': str(e),
            'source': 'Error'
        })

@app.route('/api/crypto-data')
def get_crypto_data():
    """Obtener datos de precios de crypto (mantener funcionalidad existente)"""
    try:
        # Mantener la funcionalidad existente para precios de crypto
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        crypto_data = []
        if "result" in result and "data" in result["result"]:
            for ticker in result["result"]["data"][:20]:  # Primeras 20 cryptos
                instrument_name = ticker.get("i", "")
                last_price = float(ticker.get("a", 0))
                volume_24h = float(ticker.get("v", 0))
                price_change_24h = float(ticker.get("c", 0))
                
                if "_USDT" in instrument_name and last_price > 0:
                    crypto = instrument_name.replace("_USDT", "")
                    change_percent = (price_change_24h / last_price * 100) if last_price > 0 else 0
                    
                    crypto_data.append({
                        "symbol": crypto,
                        "price": last_price,
                        "volume_24h": volume_24h,
                        "change_24h": price_change_24h,
                        "change_percent": round(change_percent, 2)
                    })
        
        return jsonify({
            "success": True,
            "data": crypto_data,
            "count": len(crypto_data),
            "source": "Crypto.com API (Market Data)"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "data": []
        })

@app.route('/api/instruments')
def get_instruments():
    """Obtener instrumentos de trading"""
    return jsonify([])

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    print("🚀 Iniciando servidor de trading real...")
    print("📡 Endpoint: http://localhost:8002/api")
    print("⚠️  NOTA: Configura tus credenciales reales de Crypto.com API para obtener datos reales")
    app.run(host='0.0.0.0', port=8002, debug=True)

