#!/usr/bin/env python3
"""
Servidor simple para probar datos reales de crypto
"""

from flask import Flask, jsonify
from flask_cors import CORS
import requests
import json

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

@app.route('/api/crypto-data')
def get_crypto_data():
    """Obtener datos reales de Crypto.com"""
    try:
        # Get real crypto prices from Crypto.com
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        # Process real data
        crypto_data = []
        if "result" in result and "data" in result["result"]:
            for ticker in result["result"]["data"][:20]:  # Get first 20 cryptos
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
            "source": "Crypto.com API"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "data": []
        })

@app.route('/api/account/balance')
def get_balance():
    """Get account balance"""
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
        ]
    })

@app.route('/api/orders/open')
def get_open_orders():
    """Get open orders"""
    return jsonify([])

@app.route('/api/orders/history')
def get_order_history():
    """Get order history"""
    return jsonify([])

@app.route('/api/instruments')
def get_instruments():
    """Get trading instruments"""
    return jsonify([])

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    print("🚀 Iniciando servidor simple para datos reales de crypto...")
    print("📡 Endpoint: http://localhost:8001/api/crypto-data")
    app.run(host='0.0.0.0', port=8001, debug=True)
