#!/usr/bin/env python3
"""
Servidor AWS actualizado para Crypto.com Exchange API v2
Funcionaba esta mañana con v1, ahora actualizado para v2
"""

import hmac
import hashlib
import time
import requests
import json
from flask import Flask, jsonify
from flask_cors import CORS
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Credenciales REALES de Crypto.com Exchange
API_KEY = "z3HWF8m292zJKABkzfXWvQ"
SECRET_KEY = "cxakp_oGDfb6D6JW396cYGz8FHmg"

# API v2 - ACTUALIZADA (funcionaba v1 esta mañana)
BASE_URL = "https://api.crypto.com/v2"
PRIVATE_URL = f"{BASE_URL}/private"

# Configuración de trading REAL
TRADE_ENABLED = True
DRY_RUN = False

def generate_signature(method, nonce, params=None):
    """Generar firma para API v2"""
    if params is None:
        params = {}
    
    # Ordenar parámetros alfabéticamente
    param_str = ""
    for key in sorted(params.keys()):
        if params[key] is not None:
            param_str += str(params[key])
    
    # Crear string para firma (método v2)
    payload = f"{method}{nonce}{API_KEY}{param_str}"
    
    # Generar firma HMAC-SHA256
    signature = hmac.new(
        SECRET_KEY.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return signature

def make_authenticated_request(method, params=None):
    """Hacer petición autenticada a API v2"""
    if params is None:
        params = {}
    
    nonce = int(time.time() * 1000)
    signature = generate_signature(method, nonce, params)
    
    headers = {
        'Content-Type': 'application/json',
        'X-CAPI-KEY': API_KEY,
        'X-CAPI-SIGNATURE': signature,
        'X-CAPI-TIMESTAMP': str(nonce),
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'X-Forwarded-For': '54.254.150.31'  # IP AWS
    }
    
    body = {
        'id': 1,
        'method': method,
        'params': params,
        'nonce': nonce
    }
    
    logger.info(f"🔐 Enviando petición autenticada REAL v2: {method}")
    logger.info(f"📝 Headers: {json.dumps(headers, indent=2)}")
    logger.info(f"📝 Body: {json.dumps(body, indent=2)}")
    
    try:
        response = requests.post(PRIVATE_URL, headers=headers, json=body, timeout=10)
        logger.info(f"📡 Respuesta: {response.status_code}")
        logger.info(f"📄 Contenido: {response.text[:200]}")
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"❌ Error API: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error en petición: {e}")
        return None

@app.route('/api/account/balance')
def get_account_balance():
    """Obtener balance de cuenta REAL"""
    logger.info("💰 Obteniendo TU balance REAL de Crypto.com EXCHANGE v2...")
    
    # Intentar diferentes métodos de la API v2
    methods_to_try = [
        'private/get-account-summary',
        'private/get-account',
        'private/get-balance'
    ]
    
    for method in methods_to_try:
        logger.info(f"🔄 Probando método: {method}")
        result = make_authenticated_request(method)
        
        if result and result.get('code') == 0:
            logger.info("✅ ¡ÉXITO! Datos reales obtenidos")
            return jsonify({
                "status": "success",
                "data": result.get('result', {}),
                "source": "Crypto.com Exchange API v2",
                "method": method
            })
        else:
            logger.warning(f"⚠️ Método {method} falló, probando siguiente...")
    
    logger.error("❌ NO se pudieron obtener datos reales de tu cuenta")
    return jsonify({
        "status": "error",
        "message": "No se pudieron obtener datos reales de Crypto.com Exchange API v2",
        "error": "Todos los métodos de API v2 fallaron"
    }), 500

@app.route('/api/orders/open')
def get_open_orders():
    """Obtener órdenes abiertas REALES"""
    logger.info("📋 Obteniendo órdenes abiertas REALES...")
    
    result = make_authenticated_request('private/get-open-orders')
    
    if result and result.get('code') == 0:
        return jsonify({
            "status": "success",
            "data": result.get('result', {}),
            "source": "Crypto.com Exchange API v2"
        })
    else:
        return jsonify({
            "status": "error",
            "message": "No se pudieron obtener órdenes abiertas"
        }), 500

@app.route('/api/orders/history')
def get_order_history():
    """Obtener historial de órdenes REAL"""
    logger.info("📜 Obteniendo historial de órdenes REAL...")
    
    result = make_authenticated_request('private/get-order-history')
    
    if result and result.get('code') == 0:
        return jsonify({
            "status": "success",
            "data": result.get('result', {}),
            "source": "Crypto.com Exchange API v2"
        })
    else:
        return jsonify({
            "status": "error",
            "message": "No se pudo obtener historial de órdenes"
        }), 500

@app.route('/api/crypto-data')
def get_crypto_data():
    """Obtener datos de criptomonedas en tiempo real"""
    try:
        # Usar API pública v2 para precios
        response = requests.get(f"{BASE_URL}/public/get-tickers", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return jsonify({
                "status": "success",
                "data": data.get('result', {}),
                "source": "Crypto.com Exchange API v2 Public"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Error obteniendo datos de mercado"
            }), 500
    except Exception as e:
        logger.error(f"❌ Error obteniendo datos de mercado: {e}")
        return jsonify({
            "status": "error",
            "message": "Error obteniendo datos de mercado"
        }), 500

@app.route('/api/instruments')
def get_instruments():
    """Obtener instrumentos disponibles"""
    try:
        response = requests.get(f"{BASE_URL}/public/get-instruments", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return jsonify({
                "status": "success",
                "data": data.get('result', {}),
                "source": "Crypto.com Exchange API v2 Public"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Error obteniendo instrumentos"
            }), 500
    except Exception as e:
        logger.error(f"❌ Error obteniendo instrumentos: {e}")
        return jsonify({
            "status": "error",
            "message": "Error obteniendo instrumentos"
        }), 500

@app.route('/api/trading/config')
def get_trading_config():
    """Configuración de trading"""
    return jsonify({
        "trade_enabled": TRADE_ENABLED,
        "dry_run": DRY_RUN,
        "message": "Trading habilitado - DRY_RUN desactivado",
        "status": "active",
        "api_version": "v2"
    })

@app.route('/api/trading/status')
def get_trading_status():
    """Estado del trading"""
    return jsonify({
        "trading_enabled": TRADE_ENABLED,
        "dry_run": DRY_RUN,
        "api_version": "v2",
        "status": "ready"
    })

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "api_configured": True,
        "credentials": "Real data from Crypto.com Exchange API v2",
        "message": "Servidor AWS con datos REALES de tu cartera - API v2",
        "trading_enabled": TRADE_ENABLED,
        "dry_run": DRY_RUN,
        "api_version": "v2"
    })

if __name__ == '__main__':
    print("🚀 Iniciando servidor AWS para Crypto.com EXCHANGE API v2...")
    print("📡 Endpoint: http://54.254.150.31:8001/api")
    print("✅ Credenciales reales configuradas")
    print("🔐 Solo datos REALES de Crypto.com EXCHANGE v2")
    print("💰 Extrayendo TUS datos reales del EXCHANGE")
    print("📊 Datos de mercado en tiempo real")
    print("✅ TRADING HABILITADO: TRUE")
    print("❌ DRY_RUN DESACTIVADO: FALSE")
    print("🔥 SISTEMA LISTO PARA TRADING REAL")
    print("🚫 NO DATOS MOCK - SOLO DATOS REALES")
    print("🆕 ACTUALIZADO A API v2 (funcionaba v1 esta mañana)")
    app.run(host='0.0.0.0', port=8001, debug=True)
