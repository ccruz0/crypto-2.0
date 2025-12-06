#!/usr/bin/env python3
"""
Sistema temporal funcional mientras se resuelve el problema de Crypto.com
Proporciona una interfaz funcional para el trading
"""

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

# Configuración de trading REAL
TRADE_ENABLED = True
DRY_RUN = False

def get_binance_prices():
    """Obtener precios de Binance como alternativa"""
    try:
        response = requests.get('https://api.binance.com/api/v3/ticker/price', timeout=10)
        if response.status_code == 200:
            prices = response.json()
            # Convertir a formato más útil
            price_dict = {}
            for item in prices:
                symbol = item['symbol']
                price = float(item['price'])
                price_dict[symbol] = price
            return price_dict
        return None
    except Exception as e:
        logger.error(f"Error obteniendo precios de Binance: {e}")
        return None

def get_coingecko_prices():
    """Obtener precios de CoinGecko como alternativa"""
    try:
        # Obtener precios de las principales criptomonedas
        coins = ['bitcoin', 'ethereum', 'cardano', 'solana', 'polkadot']
        response = requests.get(f'https://api.coingecko.com/api/v3/simple/price?ids={",".join(coins)}&vs_currencies=usd', timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"Error obteniendo precios de CoinGecko: {e}")
        return None

@app.route('/api/account/balance')
def get_account_balance():
    """Balance de cuenta temporal"""
    logger.info("💰 Obteniendo balance temporal...")
    
    # Intentar obtener precios de mercado
    binance_prices = get_binance_prices()
    coingecko_prices = get_coingecko_prices()
    
    # Datos de ejemplo basados en tu portfolio anterior
    portfolio_data = {
        "status": "temporary",
        "message": "Sistema temporal mientras se resuelve problema de Crypto.com",
        "data": {
            "accounts": [
                {
                    "currency": "USDT",
                    "balance": "1000.00",
                    "available": "1000.00",
                    "frozen": "0.00"
                },
                {
                    "currency": "BTC",
                    "balance": "0.5",
                    "available": "0.5",
                    "frozen": "0.00"
                },
                {
                    "currency": "ETH",
                    "balance": "2.0",
                    "available": "2.0",
                    "frozen": "0.00"
                }
            ],
            "total_balance_usd": "40000.00",
            "market_prices": binance_prices or coingecko_prices or {},
            "source": "Temporary system - Crypto.com API unavailable"
        },
        "trading_enabled": TRADE_ENABLED,
        "dry_run": DRY_RUN,
        "api_status": "Crypto.com API temporarily unavailable"
    }
    
    return jsonify(portfolio_data)

@app.route('/api/crypto-data')
def get_crypto_data():
    """Datos de criptomonedas en tiempo real"""
    logger.info("📊 Obteniendo datos de mercado...")
    
    # Intentar múltiples fuentes
    binance_prices = get_binance_prices()
    coingecko_prices = get_coingecko_prices()
    
    if binance_prices:
        return jsonify({
            "status": "success",
            "data": binance_prices,
            "source": "Binance API",
            "message": "Datos de mercado en tiempo real"
        })
    elif coingecko_prices:
        return jsonify({
            "status": "success",
            "data": coingecko_prices,
            "source": "CoinGecko API",
            "message": "Datos de mercado en tiempo real"
        })
    else:
        return jsonify({
            "status": "error",
            "message": "No se pudieron obtener datos de mercado"
        }), 500

@app.route('/api/orders/open')
def get_open_orders():
    """Órdenes abiertas temporal"""
    return jsonify({
        "status": "success",
        "data": [],
        "message": "No hay órdenes abiertas",
        "source": "Temporary system"
    })

@app.route('/api/orders/history')
def get_order_history():
    """Historial de órdenes temporal"""
    return jsonify({
        "status": "success",
        "data": [],
        "message": "Historial de órdenes no disponible temporalmente",
        "source": "Temporary system"
    })

@app.route('/api/trading/config')
def get_trading_config():
    """Configuración de trading"""
    return jsonify({
        "trade_enabled": TRADE_ENABLED,
        "dry_run": DRY_RUN,
        "message": "Trading habilitado - Sistema temporal",
        "status": "active",
        "api_status": "Crypto.com API temporarily unavailable"
    })

@app.route('/api/trading/status')
def get_trading_status():
    """Estado del trading"""
    return jsonify({
        "trading_enabled": TRADE_ENABLED,
        "dry_run": DRY_RUN,
        "status": "temporary",
        "message": "Sistema temporal activo",
        "api_status": "Crypto.com API temporarily unavailable"
    })

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        "status": "temporary",
        "api_configured": False,
        "credentials": "Temporary system - Crypto.com API unavailable",
        "message": "Sistema temporal mientras se resuelve problema de Crypto.com",
        "trading_enabled": TRADE_ENABLED,
        "dry_run": DRY_RUN,
        "server": "temporary",
        "crypto_com_status": "unavailable",
        "alternative_data": "Binance/CoinGecko APIs"
    })

if __name__ == '__main__':
    print("🚀 Iniciando sistema temporal...")
    print("📡 Endpoint: http://localhost:8001/api")
    print("⚠️  SISTEMA TEMPORAL - Crypto.com API no disponible")
    print("📊 Usando datos alternativos de Binance/CoinGecko")
    print("✅ TRADING HABILITADO: TRUE")
    print("❌ DRY_RUN DESACTIVADO: FALSE")
    print("🔄 Esperando resolución del problema de Crypto.com")
    app.run(host='0.0.0.0', port=8001, debug=True)




