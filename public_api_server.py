#!/usr/bin/env python3
"""
Servidor que usa solo la API pública de Crypto.com para datos de mercado
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import json
import time
from datetime import datetime
import logging

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/api/crypto-data')
def get_crypto_data():
    """Obtener datos de crypto en tiempo real desde Crypto.com"""
    try:
        logger.info("📊 Obteniendo datos de crypto en tiempo real desde Crypto.com...")
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        crypto_data = []
        if "result" in data and "data" in data["result"]:
            for ticker in data["result"]["data"][:50]:  # Top 50 cryptos
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
        
        logger.info(f"✅ Datos de crypto obtenidos: {len(crypto_data)} cryptos")
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

@app.route('/api/account/balance')
def get_mock_balance():
    """Balance mock mientras se resuelve la API privada"""
    return jsonify({
        "error": "API privada no disponible",
        "message": "La API privada de Crypto.com no está respondiendo. Verifica tus credenciales.",
        "source": "Error - API privada no disponible"
    }), 500

@app.route('/api/orders/open')
def get_mock_orders():
    """Órdenes mock mientras se resuelve la API privada"""
    return jsonify({
        "orders": [],
        "source": "API privada no disponible"
    })

@app.route('/api/orders/history')
def get_mock_history():
    """Historial mock mientras se resuelve la API privada"""
    return jsonify({
        "orders": [],
        "source": "API privada no disponible"
    })

@app.route('/api/instruments')
def get_instruments():
    """Obtener instrumentos disponibles"""
    try:
        logger.info("📋 Obteniendo instrumentos disponibles...")
        url = "https://api.crypto.com/exchange/v1/public/get-instruments"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "result" in data and "instruments" in data["result"]:
            instruments = data["result"]["instruments"]
            logger.info(f"✅ Instrumentos obtenidos: {len(instruments)}")
            return jsonify({
                "instruments": instruments,
                "count": len(instruments),
                "source": "Crypto.com Public API"
            })
        else:
            return jsonify({
                "instruments": [],
                "source": "No se pudieron obtener instrumentos"
            })
            
    except Exception as e:
        logger.error(f"❌ Error obteniendo instrumentos: {e}")
        return jsonify({
            "instruments": [],
            "error": str(e)
        })

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "api_configured": True,
        "credentials": "Solo API pública de Crypto.com",
        "message": "Usando API pública mientras se resuelve la API privada"
    })

if __name__ == '__main__':
    print("🚀 Iniciando servidor con API pública de Crypto.com...")
    print("📡 Endpoint: http://localhost:8012/api")
    print("✅ Solo API pública (datos de mercado en tiempo real)")
    print("⚠️  API privada no disponible - verifica credenciales")
    print("📊 Datos de mercado en tiempo real")
    app.run(host='0.0.0.0', port=8012, debug=True)

