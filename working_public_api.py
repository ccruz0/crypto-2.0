#!/usr/bin/env python3
"""
Servidor que funcionaba ayer - usando API pública de Crypto.com
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import json
from datetime import datetime
import logging

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/api/crypto-data')
def get_crypto_data():
    """Obtener datos de precios de crypto en tiempo real (API pública que funcionaba ayer)"""
    try:
        logger.info("📊 Obteniendo datos de crypto en tiempo real...")
        
        # Usar la API pública que funcionaba ayer
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
        
        logger.info(f"✅ Datos obtenidos: {len(crypto_data)} cryptos")
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
def get_balance():
    """Get account balance (mock data)"""
    return jsonify({
        "total_usd": 50000.0,
        "available_usd": 25000.0,
        "crypto_balance": {
            "BTC": 0.5,
            "ETH": 2.0,
            "USDT": 1000.0
        },
        "accounts": [
            {"currency": "BTC", "balance": 0.5, "available": 0.5, "frozen": 0.0},
            {"currency": "ETH", "balance": 2.0, "available": 2.0, "frozen": 0.0},
            {"currency": "USDT", "balance": 1000.0, "available": 1000.0, "frozen": 0.0}
        ]
    })

@app.route('/api/orders/open')
def get_open_orders():
    """Get open orders (mock data)"""
    return jsonify([])

@app.route('/api/orders/history')
def get_order_history():
    """Get order history (mock data)"""
    return jsonify([])

@app.route('/api/instruments')
def get_instruments():
    """Get trading instruments (mock data)"""
    return jsonify([])

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "api_configured": True,
        "credentials": "Public API (No Auth Required)",
        "message": "Conectándose a datos reales de mercado"
    })

if __name__ == '__main__':
    print("🚀 Restaurando servidor que funcionaba ayer...")
    print("📡 Endpoint: http://localhost:8001/api")
    print("✅ Usando API pública de Crypto.com (sin autenticación)")
    print("💰 Datos de mercado en tiempo real")
    app.run(host='0.0.0.0', port=8001, debug=True)

