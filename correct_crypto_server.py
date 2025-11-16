#!/usr/bin/env python3
"""
Servidor corregido para conectar a la API privada de Crypto.com
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

# URL correcta de la API privada de Crypto.com
BASE_URL = "https://api.crypto.com/v2"
PRIVATE_URL = f"{BASE_URL}/private"

def generate_signature(method, params, secret_key, nonce):
    """Generar firma HMAC-SHA256 para autenticación (método correcto)"""
    # Crear string de parámetros ordenados
    param_string = ""
    if params:
        sorted_params = sorted(params.items())
        param_string = "".join([f"{k}{v}" for k, v in sorted_params])
    
    # Crear payload para firma (formato correcto)
    payload = f"{method}{nonce}{API_KEY}{param_string}"
    
    # Generar firma HMAC-SHA256
    signature = hmac.new(
        secret_key.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return signature

def make_authenticated_request(method, params=None):
    """Realizar petición autenticada con configuración correcta"""
    try:
        nonce = int(time.time() * 1000)
        signature = generate_signature(method, params, SECRET_KEY, nonce)
        
        # Headers correctos para la API de Crypto.com
        headers = {
            'Content-Type': 'application/json',
            'X-CAPI-KEY': API_KEY,
            'X-CAPI-SIGNATURE': signature,
            'X-CAPI-TIMESTAMP': str(nonce),
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Body correcto para la API de Crypto.com
        body = {
            'id': 1,
            'method': method,
            'params': params or {},
            'nonce': nonce
        }
        
        logger.info(f"🔐 Enviando petición autenticada: {method}")
        logger.info(f"📡 URL: {PRIVATE_URL}")
        logger.info(f"🔑 API Key: {API_KEY[:10]}...")
        
        # Realizar petición con configuración correcta
        response = requests.post(
            PRIVATE_URL, 
            headers=headers, 
            json=body, 
            timeout=15,
            verify=True  # Verificar SSL
        )
        
        logger.info(f"📡 Respuesta: {response.status_code}")
        logger.info(f"📄 Headers de respuesta: {dict(response.headers)}")
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"✅ Respuesta exitosa: {result}")
            return result
        else:
            logger.error(f"❌ Error API: {response.status_code}")
            logger.error(f"❌ Contenido: {response.text[:500]}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error en petición: {e}")
        return None

@app.route('/api/account/balance')
def get_real_balance():
    """Obtener TU balance real de Crypto.com"""
    try:
        logger.info("💰 Obteniendo TU balance real de Crypto.com...")
        
        # Usar el método correcto para obtener el balance
        response = make_authenticated_request("private/get-account-summary")
        
        if response and "result" in response:
            accounts = response["result"].get("accounts", [])
            
            total_usd = 0.0
            crypto_balance = {}
            processed_accounts = []
            
            for acc in accounts:
                currency = acc.get("currency", "")
                balance = float(acc.get("balance", 0))
                available = float(acc.get("available", 0))
                frozen = float(acc.get("locked", 0))
                
                if balance > 0:
                    processed_accounts.append({
                        "currency": currency,
                        "balance": balance,
                        "available": available,
                        "frozen": frozen
                    })
                    
                    if currency == "USDT" or currency == "USD":
                        total_usd += balance
                    elif balance > 0:
                        crypto_balance[currency] = balance
            
            logger.info(f"✅ Datos reales obtenidos: {len(processed_accounts)} monedas")
            return jsonify({
                "total_usd": total_usd,
                "available_usd": total_usd * 0.8,
                "crypto_balance": crypto_balance,
                "accounts": processed_accounts,
                "source": "Crypto.com API (TU CARTERA REAL)",
                "timestamp": datetime.now().isoformat()
            })
        else:
            logger.warning("❌ No se pudieron obtener datos reales de tu cuenta")
            return jsonify({
                "error": "No se pudieron obtener datos de tu cuenta",
                "message": "Verifica que tus credenciales sean correctas y que tengas fondos en tu cuenta",
                "source": "Error - Verificar credenciales"
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Error obteniendo balance: {e}")
        return jsonify({
            "error": str(e),
            "source": "Error"
        }), 500

@app.route('/api/orders/open')
def get_real_open_orders():
    """Obtener TUS órdenes abiertas reales"""
    try:
        logger.info("📋 Obteniendo TUS órdenes abiertas reales...")
        
        response = make_authenticated_request("private/get-open-orders")
        
        if response and "result" in response:
            orders = response["result"].get("order_list", [])
            logger.info(f"✅ Órdenes reales obtenidas: {len(orders)} órdenes")
            return jsonify({
                "orders": orders,
                "source": "Crypto.com API (TUS ÓRDENES REALES)"
            })
        else:
            return jsonify({
                "orders": [],
                "source": "No hay órdenes abiertas"
            })
            
    except Exception as e:
        logger.error(f"❌ Error obteniendo órdenes abiertas: {e}")
        return jsonify({"orders": [], "error": str(e)})

@app.route('/api/orders/history')
def get_real_order_history():
    """Obtener TU historial de órdenes reales"""
    try:
        logger.info("📊 Obteniendo TU historial de órdenes reales...")
        
        response = make_authenticated_request("private/get-order-history")
        
        if response and "result" in response:
            orders = response["result"].get("order_list", [])
            logger.info(f"✅ Historial real obtenido: {len(orders)} órdenes")
            return jsonify({
                "orders": orders,
                "source": "Crypto.com API (TU HISTORIAL REAL)"
            })
        else:
            return jsonify({
                "orders": [],
                "source": "No hay historial de órdenes"
            })
            
    except Exception as e:
        logger.error(f"❌ Error obteniendo historial de órdenes: {e}")
        return jsonify({"orders": [], "error": str(e)})

@app.route('/api/crypto-data')
def get_crypto_data():
    """Obtener datos de precios de crypto en tiempo real"""
    try:
        logger.info("📊 Obteniendo datos de crypto en tiempo real...")
        
        # Usar la API pública de Crypto.com para datos de mercado
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
        
        return jsonify({
            "success": True,
            "data": crypto_data,
            "count": len(crypto_data),
            "source": "Crypto.com Public API (Real Market Data)"
        })
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo datos de crypto: {e}")
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
        "credentials": "Real Crypto.com API",
        "message": "Conectándose a TU cartera real"
    })

if __name__ == '__main__':
    print("🚀 Iniciando servidor corregido para Crypto.com...")
    print("📡 Endpoint: http://localhost:8001/api")
    print("✅ Credenciales reales configuradas")
    print("🔑 API Key:", API_KEY[:10] + "...")
    print("💰 Extrayendo datos de TU cartera real")
    print("📊 Datos de mercado en tiempo real")
    app.run(host='0.0.0.0', port=8001, debug=True)

