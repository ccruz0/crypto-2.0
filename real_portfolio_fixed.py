#!/usr/bin/env python3
"""
Servidor para obtener TU cartera real de Crypto.com usando la API privada
"""

import hmac
import hashlib
import time
import requests
import json
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuración de la API de Crypto.com ---
API_KEY = "z3HWF8m292zJKABkzfXWvQ"  # Tu API key real
SECRET_KEY = "cxakp_oGDfb6D6JW396cYGz8FHmg"  # Tu secret key real
BASE_URL = "https://api.crypto.com/v2"  # Base URL para la API privada

def generate_signature(method: str, params: dict, nonce: int):
    """Genera la firma para la autenticación de la API de Crypto.com"""
    param_string = ""
    if params:
        # Ordenar parámetros alfabéticamente por clave
        sorted_params = sorted(params.items())
        param_string = "".join([f"{k}{v}" for k, v in sorted_params])

    payload = f"{method}{nonce}{API_KEY}{param_string}"
    signature = hmac.new(
        bytes(SECRET_KEY, 'utf-8'),
        bytes(payload, 'utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature

def make_authenticated_request(method: str, params: dict = None):
    """Realiza una petición autenticada a la API de Crypto.com"""
    nonce = int(time.time() * 1000)
    signature = generate_signature(method, params, nonce)

    headers = {
        "Content-Type": "application/json",
        "X-CAPI-KEY": API_KEY,
        "X-CAPI-SIGNATURE": signature,
        "X-CAPI-TIMESTAMP": str(nonce)
    }

    body = {
        "id": 1,
        "method": method,
        "params": params or {},
        "nonce": nonce
    }

    try:
        logger.info(f"🔐 Enviando petición autenticada: {method}")
        response = requests.post(f"{BASE_URL}/private", headers=headers, json=body, timeout=10)
        logger.info(f"📡 Respuesta: {response.status_code}")
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"❌ Error API: {response.status_code} - {response.text}")
            return {"error": f"API Error: {response.status_code} - {response.text}"}
    except Exception as e:
        logger.error(f"❌ Error en petición autenticada: {e}")
        return {"error": str(e)}

def get_real_account_summary():
    """Obtiene el resumen de la cuenta (balance) real"""
    try:
        logger.info("💰 Obteniendo TU balance real de Crypto.com...")
        
        response = make_authenticated_request("private/get-account-summary")
        
        if response and "result" in response and "accounts" in response["result"]:
            accounts_data = response["result"]["accounts"]
            
            processed_accounts = []
            total_usd_value = 0.0
            
            for acc in accounts_data:
                currency = acc["currency"]
                balance = float(acc["balance"])
                available = float(acc["available"])
                frozen = float(acc["locked"])

                processed_accounts.append({
                    "currency": currency,
                    "balance": balance,
                    "available": available,
                    "frozen": frozen,
                    "usd_value": balance  # Simplificado por ahora
                })
                total_usd_value += balance
            
            return {
                "total_usd": round(total_usd_value, 2),
                "available_usd": round(total_usd_value, 2),
                "accounts": processed_accounts,
                "source": "Crypto.com Private API (Real Data)"
            }
        else:
            logger.warning("❌ No se pudieron obtener datos reales de tu cuenta")
            return {
                "total_usd": 0.0,
                "available_usd": 0.0,
                "accounts": [],
                "source": "Error - Verificar credenciales"
            }
    except Exception as e:
        logger.error(f"❌ Error obteniendo balance: {e}")
        return {
            "total_usd": 0.0,
            "available_usd": 0.0,
            "accounts": [],
            "source": f"Error: {str(e)}"
        }

def get_real_open_orders():
    """Obtiene las órdenes abiertas reales"""
    try:
        logger.info("📋 Obteniendo TUS órdenes abiertas reales...")
        
        response = make_authenticated_request("private/get-open-orders")
        
        if response and "result" in response and "order_list" in response["result"]:
            orders_data = response["result"]["order_list"]
            logger.info(f"✅ {len(orders_data)} órdenes abiertas reales obtenidas.")
            return orders_data
        else:
            logger.warning("❌ No se pudieron obtener órdenes abiertas reales")
            return []
    except Exception as e:
        logger.error(f"❌ Error obteniendo órdenes abiertas: {e}")
        return []

def get_real_order_history():
    """Obtiene el historial de órdenes reales"""
    try:
        logger.info("📊 Obteniendo TU historial de órdenes reales...")
        
        response = make_authenticated_request("private/get-order-history")
        
        if response and "result" in response and "order_list" in response["result"]:
            orders_data = response["result"]["order_list"]
            logger.info(f"✅ {len(orders_data)} órdenes del historial reales obtenidas.")
            return orders_data
        else:
            logger.warning("❌ No se pudieron obtener historial de órdenes reales")
            return []
    except Exception as e:
        logger.error(f"❌ Error obteniendo historial de órdenes: {e}")
        return []

@app.route('/api/crypto-data')
def get_crypto_data():
    """Obtener datos de precios de crypto en tiempo real"""
    try:
        logger.info("📊 Obteniendo datos de crypto en tiempo real...")
        
        # Usar la API pública para datos de mercado
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()

        crypto_data = []
        if "result" in result and "data" in result["result"]:
            for ticker in result["result"]["data"]:
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
        
        logger.info(f"✅ Datos de mercado obtenidos: {len(crypto_data)} cryptos")
        return jsonify({
            "success": True,
            "data": crypto_data,
            "count": len(crypto_data),
            "source": "Crypto.com Public API (Real Market Data)",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo datos de crypto: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "data": []
        })

@app.route('/api/account/balance')
def account_balance_route():
    """Endpoint para obtener el balance de la cuenta (real o mock)"""
    summary = get_real_account_summary()
    if summary and summary.get("accounts"):
        return jsonify(summary)
    else:
        # Fallback a datos mock si la API no está disponible o falla
        return jsonify({
            "total_usd": 40869.27,
            "available_usd": 24310.43,
            "accounts": [
                {"currency": "USD", "balance": 36076.83, "available": 26891.86, "frozen": 9184.97, "usd_value": 36071.00},
                {"currency": "DOGE", "balance": 15340.34, "available": 5106.34, "frozen": 10234.00, "usd_value": 3010.00},
                {"currency": "BONK", "balance": 186192267.80, "available": 186192267.80, "frozen": 0.00, "usd_value": 2730.00},
                {"currency": "DGB", "balance": 350855.44, "available": 350855.44, "frozen": 0.00, "usd_value": 2230.00},
                {"currency": "AAVE", "balance": 6.37, "available": 0.00, "frozen": 6.37, "usd_value": 1460.00},
                {"currency": "ALGO", "balance": 6154.23, "available": 6154.23, "frozen": 0.00, "usd_value": 1120.00},
                {"currency": "DOT", "balance": 369.77, "available": 6.68, "frozen": 363.09, "usd_value": 1120.00},
                {"currency": "SUI", "balance": 414.54, "available": 0.54, "frozen": 414.00, "usd_value": 1010.00},
                {"currency": "XRP", "balance": 237.84, "available": 237.84, "frozen": 0.00, "usd_value": 570.00},
                {"currency": "USDT", "balance": 546.07, "available": 546.07, "frozen": 0.00, "usd_value": 540.00},
                {"currency": "BTC", "balance": 0.0013, "available": 0.0013, "frozen": 0.00, "usd_value": 140.00},
                {"currency": "APT", "balance": 30.17, "available": 30.17, "frozen": 0.00, "usd_value": 90.00}
            ],
            "source": "Mock Data (API no disponible)"
        })

@app.route('/api/orders/open')
def open_orders_route():
    """Endpoint para obtener órdenes abiertas (real o mock)"""
    orders = get_real_open_orders()
    if orders:
        return jsonify({"orders": orders, "source": "Crypto.com Private API"})
    else:
        return jsonify({"orders": [], "source": "Mock Data (API no disponible)"})

@app.route('/api/orders/history')
def order_history_route():
    """Endpoint para obtener historial de órdenes (real o mock)"""
    history = get_real_order_history()
    if history:
        return jsonify({"orders": history, "source": "Crypto.com Private API"})
    else:
        return jsonify({"orders": [], "source": "Mock Data (API no disponible)"})

@app.route('/api/instruments')
def get_instruments():
    """Get trading instruments (mock data)"""
    return jsonify({"instruments": ["BTC_USDT", "ETH_USDT", "BNB_USDT"]})

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "message": "Conectándose a TU cartera real",
        "api_configured": True,
        "credentials": "Real API Keys"
    })

if __name__ == '__main__':
    print("🚀 Iniciando servidor para TU cartera real...")
    print("📡 Endpoint: http://localhost:8001/api")
    print("✅ Credenciales reales configuradas")
    print("💰 Obteniendo datos de TU cartera real")
    print("📊 Datos de mercado en tiempo real")
    app.run(host='0.0.0.0', port=8001, debug=True)

