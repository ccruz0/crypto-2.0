#!/usr/bin/env python3
"""
Servidor optimizado para datos de criptomonedas
Carga todas las monedas de esta mañana con rate limiting optimizado
"""

from flask import Flask, jsonify, request
import requests
import json
from datetime import datetime
import time
import random

app = Flask(__name__)

# Add CORS headers manually
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Lista de todas las monedas que agregamos esta mañana
MORNING_CRYPTOS = [
    "BTC", "ETH", "BNB", "XRP", "ADA", "SOL", "DOT", "AVAX", "MATIC", "LINK",
    "UNI", "LTC", "BCH", "ATOM", "NEAR", "ALGO", "VET", "ICP", "FIL", "TRX",
    "ETC", "XLM", "MANA", "SAND", "AXS", "CHZ", "ENJ", "BAT", "ZEC", "DASH"
]

# Cache para evitar peticiones repetidas
crypto_cache = {}
cache_timeout = 30  # 30 segundos

def get_binance_data_optimized():
    """Obtener datos de Binance optimizado"""
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        crypto_data = []
        for ticker in data:
            symbol = ticker.get('symbol', '')
            if symbol.endswith('USDT') and float(ticker.get('lastPrice', 0)) > 0:
                crypto = symbol.replace('USDT', '')
                if crypto in MORNING_CRYPTOS:  # Solo las monedas de esta mañana
                    price = float(ticker.get('lastPrice', 0))
                    change_24h = float(ticker.get('priceChangePercent', 0))
                    volume = float(ticker.get('volume', 0))
                    
                    crypto_data.append({
                        "symbol": crypto,
                        "price": price,
                        "change_24h": change_24h,
                        "change_percent": change_24h,
                        "volume_24h": volume,
                        "source": "Binance"
                    })
        
        return crypto_data
    except Exception as e:
        print(f"Error Binance: {e}")
        return []

def get_cryptocom_data_optimized():
    """Obtener datos de Crypto.com optimizado"""
    try:
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        result = response.json()
        
        crypto_data = []
        if "result" in result and "data" in result["result"]:
            for ticker in result["result"]["data"]:
                instrument_name = ticker.get("i", "")
                last_price = float(ticker.get("a", 0))
                price_change_24h = float(ticker.get("c", 0))
                volume_24h = float(ticker.get("v", 0))
                
                if "_USDT" in instrument_name and last_price > 0:
                    crypto = instrument_name.replace("_USDT", "")
                    if crypto in MORNING_CRYPTOS:  # Solo las monedas de esta mañana
                        change_percent = (price_change_24h / last_price * 100) if last_price > 0 else 0
                        
                        crypto_data.append({
                            "symbol": crypto,
                            "price": last_price,
                            "change_24h": price_change_24h,
                            "change_percent": round(change_percent, 2),
                            "volume_24h": volume_24h,
                            "source": "Crypto.com"
                        })
        
        return crypto_data
    except Exception as e:
        print(f"Error Crypto.com: {e}")
        return []

def get_coingecko_data_optimized():
    """Obtener datos de CoinGecko optimizado con rate limiting"""
    try:
        # Usar cache para evitar rate limiting
        cache_key = "coingecko_data"
        if cache_key in crypto_cache:
            cache_time, data = crypto_cache[cache_key]
            if time.time() - cache_time < cache_timeout:
                return data
        
        # Esperar un poco para evitar rate limiting
        time.sleep(random.uniform(1, 3))
        
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            'vs_currency': 'usd',
            'order': 'market_cap_desc',
            'per_page': 50,  # Más monedas
            'page': 1
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        crypto_data = []
        for coin in data:
            symbol = coin.get('symbol', '').upper()
            if symbol in MORNING_CRYPTOS:  # Solo las monedas de esta mañana
                price = float(coin.get('current_price', 0))
                change_24h = float(coin.get('price_change_percentage_24h', 0))
                volume = float(coin.get('total_volume', 0))
                
                crypto_data.append({
                    "symbol": symbol,
                    "price": price,
                    "change_24h": change_24h,
                    "change_percent": change_24h,
                    "volume_24h": volume,
                    "source": "CoinGecko"
                })
        
        # Guardar en cache
        crypto_cache[cache_key] = (time.time(), crypto_data)
        return crypto_data
        
    except Exception as e:
        print(f"Error CoinGecko: {e}")
        return []

def get_fallback_data():
    """Datos de fallback cuando las APIs fallan"""
    fallback_data = []
    for crypto in MORNING_CRYPTOS[:10]:  # Primeras 10 monedas
        # Precios aproximados de esta mañana
        prices = {
            "BTC": 67000, "ETH": 3600, "BNB": 600, "XRP": 0.6, "ADA": 0.5,
            "SOL": 100, "DOT": 7, "AVAX": 35, "MATIC": 0.8, "LINK": 15
        }
        
        price = prices.get(crypto, 1.0)
        change = random.uniform(-5, 5)  # Cambio aleatorio entre -5% y +5%
        
        fallback_data.append({
            "symbol": crypto,
            "price": price,
            "change_24h": change,
            "change_percent": change,
            "volume_24h": random.uniform(1000000, 10000000),
            "source": "Fallback"
        })
    
    return fallback_data

def aggregate_crypto_data_optimized():
    """Agregar datos de múltiples fuentes optimizado"""
    all_data = []
    
    # Obtener datos de fuentes disponibles
    sources = [
        ("Binance", get_binance_data_optimized),
        ("Crypto.com", get_cryptocom_data_optimized),
        ("CoinGecko", get_coingecko_data_optimized)
    ]
    
    successful_sources = 0
    for source_name, source_func in sources:
        try:
            data = source_func()
            all_data.extend(data)
            successful_sources += 1
            print(f"✅ {source_name}: {len(data)} cryptos")
        except Exception as e:
            print(f"❌ {source_name}: Error - {e}")
    
    # Si no hay fuentes exitosas, usar datos de fallback
    if successful_sources == 0:
        print("⚠️ Todas las fuentes fallaron, usando datos de fallback")
        all_data = get_fallback_data()
    
    # Agrupar por símbolo y calcular promedio
    symbol_data = {}
    for item in all_data:
        symbol = item['symbol']
        if symbol not in symbol_data:
            symbol_data[symbol] = {
                'symbol': symbol,
                'prices': [],
                'changes': [],
                'volumes': [],
                'sources': []
            }
        
        symbol_data[symbol]['prices'].append(item['price'])
        symbol_data[symbol]['changes'].append(item['change_percent'])
        symbol_data[symbol]['volumes'].append(item['volume_24h'])
        symbol_data[symbol]['sources'].append(item['source'])
    
    # Calcular promedios
    aggregated_data = []
    for symbol, data in symbol_data.items():
        if len(data['prices']) > 0:
            avg_price = sum(data['prices']) / len(data['prices'])
            avg_change = sum(data['changes']) / len(data['changes'])
            avg_volume = sum(data['volumes']) / len(data['volumes'])
            
            aggregated_data.append({
                "symbol": symbol,
                "price": round(avg_price, 6),
                "change_24h": round(avg_change, 2),
                "change_percent": round(avg_change, 2),
                "volume_24h": round(avg_volume, 2),
                "sources": data['sources'],
                "source_count": len(data['sources'])
            })
    
    return aggregated_data

@app.route('/api/crypto-data')
def get_crypto_data():
    """Obtener datos agregados de múltiples fuentes"""
    try:
        print(f"🔄 Obteniendo datos de múltiples fuentes... {datetime.now().strftime('%H:%M:%S')}")
        
        aggregated_data = aggregate_crypto_data_optimized()
        
        return jsonify({
            "success": True,
            "data": aggregated_data,
            "count": len(aggregated_data),
            "sources": ["Binance", "CoinGecko", "Crypto.com"],
            "timestamp": datetime.now().isoformat(),
            "morning_cryptos": MORNING_CRYPTOS
        })
    except Exception as e:
        print(f"❌ Error general: {e}")
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
    print("🚀 Iniciando servidor optimizado para datos de crypto...")
    print(f"📡 Monedas de esta mañana: {len(MORNING_CRYPTOS)} cryptos")
    print("🌐 Endpoint: http://localhost:8001/api/crypto-data")
    app.run(host='0.0.0.0', port=8001, debug=False)

