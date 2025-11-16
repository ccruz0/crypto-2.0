#!/usr/bin/env python3
"""
Servidor para configurar manualmente TU cartera real
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

# Configuración de TU cartera real
# MODIFICA ESTOS VALORES CON TUS DATOS REALES
REAL_PORTFOLIO = {
    "total_usd": 0.0,  # Cambia por tu valor total real
    "crypto_balance": {
        # Ejemplo: "BTC": 0.1, "ETH": 2.5, "USDT": 500.0
        # Agrega tus monedas reales aquí
    },
    "accounts": [
        # Ejemplo de formato:
        # {"currency": "BTC", "balance": 0.1, "available": 0.1, "frozen": 0.0},
        # {"currency": "ETH", "balance": 2.5, "available": 2.5, "frozen": 0.0},
    ]
}

@app.route('/api/account/balance')
def get_manual_balance():
    """Obtener balance configurado manualmente"""
    try:
        logger.info("📊 Obteniendo datos de cartera configurados...")
        
        # Verificar si hay datos configurados
        if not REAL_PORTFOLIO["accounts"]:
            return jsonify({
                "error": "No hay datos de cartera configurados",
                "message": "Configura tus datos reales en el servidor",
                "instructions": "Edita el archivo manual_portfolio_server.py y agrega tus datos reales",
                "source": "Configuración requerida"
            }), 400
        
        return jsonify({
            "total_usd": REAL_PORTFOLIO["total_usd"],
            "available_usd": REAL_PORTFOLIO["total_usd"] * 0.8,
            "crypto_balance": REAL_PORTFOLIO["crypto_balance"],
            "accounts": REAL_PORTFOLIO["accounts"],
            "source": "Datos configurados manualmente (TUS DATOS REALES)"
        })
            
    except Exception as e:
        logger.error(f"Error obteniendo balance: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/orders/open')
def get_manual_open_orders():
    """Obtener órdenes abiertas"""
    return jsonify({
        "orders": [],
        "source": "No hay órdenes abiertas configuradas"
    })

@app.route('/api/orders/history')
def get_manual_order_history():
    """Obtener historial de órdenes"""
    return jsonify({
        "orders": [],
        "source": "No hay historial configurado"
    })

@app.route('/api/crypto-data')
def get_crypto_data():
    """Obtener datos de precios de crypto en tiempo real"""
    try:
        logger.info("📊 Obteniendo datos de crypto en tiempo real...")
        
        # Obtener datos de Binance (más confiable)
        url = "https://api.binance.com/api/v3/ticker/24hr"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        crypto_data = []
        for ticker in data[:20]:  # Primeras 20 cryptos
            symbol = ticker.get('symbol', '')
            if symbol.endswith('USDT') and float(ticker.get('lastPrice', 0)) > 0:
                crypto = symbol.replace('USDT', '')
                price = float(ticker.get('lastPrice', 0))
                change_24h = float(ticker.get('priceChangePercent', 0))
                
                crypto_data.append({
                    "symbol": crypto,
                    "price": price,
                    "volume_24h": float(ticker.get('quoteVolume', 0)),
                    "change_24h": float(ticker.get('priceChange', 0)),
                    "change_percent": change_24h
                })
        
        return jsonify({
            "success": True,
            "data": crypto_data,
            "count": len(crypto_data),
            "source": "Binance API (Real Market Data)"
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
        "message": "Servidor de cartera manual",
        "instructions": "Configura tus datos reales en el archivo"
    })

if __name__ == '__main__':
    print("🚀 Iniciando servidor de cartera manual...")
    print("📡 Endpoint: http://localhost:8001/api")
    print("⚠️  IMPORTANTE: Configura tus datos reales en el archivo")
    print("📝 Edita manual_portfolio_server.py con tus datos reales")
    app.run(host='0.0.0.0', port=8001, debug=True)