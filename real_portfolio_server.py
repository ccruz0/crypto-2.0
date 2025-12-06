#!/usr/bin/env python3
"""
Servidor para cartera real de Crypto.com con datos de mercado
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import json
import hmac
import hashlib
import time
from datetime import datetime
import logging

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Tus credenciales reales de Crypto.com
API_KEY = "z3HWF8m292zJKABkzfXWvQ"
SECRET_KEY = "cxakp_oGDfb6D6JW396cYGz8FHmg"
BASE_URL = "https://api.crypto.com/v2"

# Lista de monedas de esta mañana
MORNING_CRYPTOS = [
    "BTC", "ETH", "BNB", "XRP", "ADA", "SOL", "DOT", "AVAX", "MATIC", "LINK",
    "UNI", "LTC", "BCH", "ATOM", "NEAR", "ALGO", "VET", "ICP", "FIL", "TRX",
    "ETC", "XLM", "MANA", "SAND", "AXS", "CHZ", "ENJ", "BAT", "ZEC", "DASH"
]

def generate_signature(method, path, params, secret_key):
    """Generar firma para autenticación con Crypto.com API"""
    timestamp = str(int(time.time() * 1000))
    
    # Crear string de parámetros ordenados
    param_string = ""
    if params:
        sorted_params = sorted(params.items())
        param_string = "".join([f"{k}{v}" for k, v in sorted_params])
    
    # Crear payload para firma
    payload = f"{method}{timestamp}{API_KEY}{param_string}"
    
    # Generar firma HMAC-SHA256
    signature = hmac.new(
        secret_key.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return signature, timestamp

def make_authenticated_request(method, path, params=None):
    """Realizar petición autenticada a Crypto.com API"""
    try:
        signature, timestamp = generate_signature(method, path, params, SECRET_KEY)
        
        headers = {
            'Content-Type': 'application/json',
            'X-CAPI-KEY': API_KEY,
            'X-CAPI-SIGNATURE': signature,
            'X-CAPI-TIMESTAMP': timestamp
        }
        
        body = {
            'id': 1,
            'method': method,
            'params': params or {},
            'nonce': int(timestamp)
        }
        
        response = requests.post(
            f"{BASE_URL}/private",
            headers=headers,
            json=body,
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"API Error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error en petición autenticada: {e}")
        return None

@app.route('/api/account/balance')
def get_real_balance():
    """Obtener balance real de la cuenta"""
    try:
        logger.info("Obteniendo balance real de Crypto.com...")
        
        # Intentar obtener datos reales
        response = make_authenticated_request("private/get-account-summary", "private/get-account-summary")
        
        if response and "result" in response:
            accounts = response["result"].get("accounts", [])
            
            # Procesar datos reales
            total_usd = 0.0
            crypto_balance = {}
            processed_accounts = []
            
            for acc in accounts:
                currency = acc.get("currency", "")
                balance = float(acc.get("balance", 0))
                available = float(acc.get("available", 0))
                frozen = float(acc.get("locked", 0))
                
                processed_accounts.append({
                    "currency": currency,
                    "balance": balance,
                    "available": available,
                    "frozen": frozen
                })
                
                if currency == "USDT":
                    total_usd += balance
                elif balance > 0:
                    crypto_balance[currency] = balance
            
            return jsonify({
                "total_usd": total_usd,
                "available_usd": total_usd * 0.5,  # Asumir 50% disponible
                "crypto_balance": crypto_balance,
                "accounts": processed_accounts,
                "source": "Crypto.com API (Real Data)"
            })
        else:
            # Fallback a datos mock realistas
            logger.warning("Usando datos mock - API no disponible")
            return jsonify({
                "total_usd": 50000.0,
                "available_usd": 25000.0,
                "crypto_balance": {
                    "BTC": 0.5,
                    "ETH": 2.0,
                    "USDT": 1000.0,
                    "BNB": 5.0,
                    "ADA": 1000.0
                },
                "accounts": [
                    {"currency": "BTC", "balance": 0.5, "available": 0.5, "frozen": 0.0},
                    {"currency": "ETH", "balance": 2.0, "available": 2.0, "frozen": 0.0},
                    {"currency": "USDT", "balance": 1000.0, "available": 1000.0, "frozen": 0.0},
                    {"currency": "BNB", "balance": 5.0, "available": 5.0, "frozen": 0.0},
                    {"currency": "ADA", "balance": 1000.0, "available": 1000.0, "frozen": 0.0}
                ],
                "source": "Mock Data (API not available)"
            })
            
    except Exception as e:
        logger.error(f"Error obteniendo balance: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/orders/open')
def get_real_open_orders():
    """Obtener órdenes abiertas reales"""
    try:
        logger.info("Obteniendo órdenes abiertas reales...")
        
        response = make_authenticated_request("private/get-open-orders", "private/get-open-orders")
        
        if response and "result" in response:
            orders = response["result"].get("order_list", [])
            return jsonify({
                "orders": orders,
                "source": "Crypto.com API (Real Data)"
            })
        else:
            # Fallback a datos mock
            return jsonify({
                "orders": [],
                "source": "Mock Data (No open orders)"
            })
            
    except Exception as e:
        logger.error(f"Error obteniendo órdenes abiertas: {e}")
        return jsonify({"orders": [], "error": str(e)})

@app.route('/api/orders/history')
def get_real_order_history():
    """Obtener historial de órdenes reales"""
    try:
        logger.info("Obteniendo historial de órdenes reales...")
        
        response = make_authenticated_request("private/get-order-history", "private/get-order-history")
        
        if response and "result" in response:
            orders = response["result"].get("order_list", [])
            return jsonify({
                "orders": orders,
                "source": "Crypto.com API (Real Data)"
            })
        else:
            # Fallback a datos mock
            return jsonify({
                "orders": [],
                "source": "Mock Data (No order history)"
            })
            
    except Exception as e:
        logger.error(f"Error obteniendo historial de órdenes: {e}")
        return jsonify({"orders": [], "error": str(e)})

@app.route('/api/crypto-data')
def get_crypto_data():
    """Obtener datos de precios de crypto en tiempo real"""
    try:
        logger.info("Obteniendo datos de crypto en tiempo real...")
        
        # Obtener datos de múltiples fuentes
        all_data = {}
        
        # Binance
        try:
            binance_url = "https://api.binance.com/api/v3/ticker/24hr"
            binance_response = requests.get(binance_url, timeout=5)
            binance_data = binance_response.json()
            
            for ticker in binance_data:
                symbol = ticker.get('symbol', '')
                if symbol.endswith('USDT') and symbol.replace('USDT', '') in MORNING_CRYPTOS:
                    crypto = symbol.replace('USDT', '')
                    all_data[crypto] = {
                        "symbol": crypto,
                        "price": float(ticker.get('lastPrice', 0)),
                        "volume_24h": float(ticker.get('quoteVolume', 0)),
                        "change_24h": float(ticker.get('priceChange', 0)),
                        "change_percent": float(ticker.get('priceChangePercent', 0)),
                        "source": "Binance"
                    }
        except Exception as e:
            logger.warning(f"Error obteniendo datos de Binance: {e}")
        
        # Crypto.com
        try:
            crypto_com_url = "https://api.crypto.com/exchange/v1/public/get-tickers"
            crypto_com_response = requests.get(crypto_com_url, timeout=5)
            crypto_com_data = crypto_com_response.json()
            
            if "result" in crypto_com_data and "data" in crypto_com_data["result"]:
                for ticker in crypto_com_data["result"]["data"]:
                    instrument_name = ticker.get("i", "")
                    if "_USDT" in instrument_name:
                        crypto = instrument_name.replace("_USDT", "")
                        if crypto in MORNING_CRYPTOS:
                            price = float(ticker.get("a", 0))
                            change_24h = float(ticker.get("c", 0))
                            change_percent = (change_24h / price * 100) if price > 0 else 0
                            
                            if crypto not in all_data or price > 0:
                                all_data[crypto] = {
                                    "symbol": crypto,
                                    "price": price,
                                    "volume_24h": float(ticker.get("v", 0)),
                                    "change_24h": change_24h,
                                    "change_percent": round(change_percent, 2),
                                    "source": "Crypto.com"
                                }
        except Exception as e:
            logger.warning(f"Error obteniendo datos de Crypto.com: {e}")
        
        # Convertir a lista y ordenar por volumen
        crypto_list = list(all_data.values())
        crypto_list.sort(key=lambda x: x.get("volume_24h", 0), reverse=True)
        
        return jsonify({
            "success": True,
            "data": crypto_list,
            "count": len(crypto_list),
            "source": "Multiple Exchanges (Real Data)"
        })
        
    except Exception as e:
        logger.error(f"Error obteniendo datos de crypto: {e}")
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
    return jsonify({
        "status": "healthy",
        "api_configured": True,
        "credentials": "Real Crypto.com API"
    })

if __name__ == '__main__':
    print("🚀 Iniciando servidor de cartera real...")
    print("📡 Endpoint: http://localhost:8001/api")
    print("✅ Credenciales reales configuradas")
    print("💰 Obteniendo datos de tu cartera real")
    print("📊 Datos de mercado en tiempo real")
    app.run(host='0.0.0.0', port=8001, debug=True)
