#!/usr/bin/env python3
"""
Script para comparar los datos de Crypto.com Exchange con los datos del dashboard
Verifica si los precios y RSI coinciden entre ambas fuentes
"""

import sys
import os
import requests
import json
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice, MarketData

def get_crypto_com_price(symbol: str) -> dict:
    """Obtener precio actual desde Crypto.com API"""
    try:
        # Normalizar símbolo para Crypto.com (BTC_USDT -> BTC_USDT, BTC_USD -> BTC_USD)
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "result" in data and "data" in data["result"]:
            for ticker in data["result"]["data"]:
                instrument_name = ticker.get("i", "")
                if instrument_name == symbol:
                    return {
                        "symbol": instrument_name,
                        "price": float(ticker.get("a", 0)),  # Ask price (last price)
                        "bid": float(ticker.get("b", 0)),    # Bid price
                        "volume_24h": float(ticker.get("v", 0)),
                        "change_24h": float(ticker.get("c", 0)),
                        "timestamp": datetime.now().isoformat()
                    }
        return None
    except Exception as e:
        print(f"❌ Error obteniendo precio de Crypto.com para {symbol}: {e}")
        return None

def get_crypto_com_ohlcv(symbol: str, interval: str = "1h", limit: int = 200) -> list:
    """Obtener datos OHLCV desde Crypto.com API"""
    try:
        url = f"https://api.crypto.com/exchange/v1/public/get-candlestick"
        params = {
            "instrument_name": symbol,
            "timeframe": interval
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "result" in data and "data" in data["result"]:
            return data["result"]["data"]
        return []
    except Exception as e:
        print(f"❌ Error obteniendo OHLCV de Crypto.com para {symbol}: {e}")
        return []

def calculate_rsi(prices: list, period: int = 14) -> float:
    """Calcular RSI desde precios de cierre"""
    if len(prices) < period + 1:
        return None
    
    # Calcular cambios
    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    
    # Separar ganancias y pérdidas
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]
    
    # Calcular promedio de ganancias y pérdidas
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 2)

def get_dashboard_data(symbol: str) -> dict:
    """Obtener datos del dashboard desde la base de datos"""
    db = SessionLocal()
    try:
        # Buscar en watchlist
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol.upper(),
            WatchlistItem.is_deleted == False
        ).first()
        
        # Buscar en MarketPrice
        market_price = db.query(MarketPrice).filter(
            MarketPrice.symbol == symbol.upper()
        ).first()
        
        # Buscar en MarketData
        market_data = db.query(MarketData).filter(
            MarketData.symbol == symbol.upper()
        ).first()
        
        return {
            "watchlist": {
                "price": watchlist_item.price if watchlist_item else None,
                "rsi": watchlist_item.rsi if watchlist_item else None,
                "atr": watchlist_item.atr if watchlist_item else None,
                "updated_at": watchlist_item.updated_at.isoformat() if watchlist_item and watchlist_item.updated_at else None
            },
            "market_price": {
                "price": market_price.price if market_price else None,
                "updated_at": market_price.updated_at.isoformat() if market_price and market_price.updated_at else None
            },
            "market_data": {
                "rsi": market_data.rsi if market_data else None,
                "atr": market_data.atr if market_data else None,
                "updated_at": market_data.updated_at.isoformat() if market_data and market_data.updated_at else None
            }
        }
    finally:
        db.close()

def compare_data(symbol: str):
    """Comparar datos entre Crypto.com y el dashboard"""
    print(f"\n{'='*80}")
    print(f"🔍 Comparando datos para {symbol}")
    print(f"{'='*80}\n")
    
    # Obtener datos de Crypto.com
    print("📡 Obteniendo datos de Crypto.com...")
    crypto_com_price = get_crypto_com_price(symbol)
    
    if not crypto_com_price:
        print(f"❌ No se encontró {symbol} en Crypto.com API")
        return
    
    print(f"✅ Precio desde Crypto.com: ${crypto_com_price['price']:,.2f}")
    
    # Obtener OHLCV para calcular RSI
    print("📊 Obteniendo datos OHLCV para calcular RSI...")
    ohlcv_data = get_crypto_com_ohlcv(symbol, interval="1h", limit=200)
    
    crypto_com_rsi = None
    if ohlcv_data and len(ohlcv_data) >= 15:
        closes = [float(candle.get("c", 0)) for candle in ohlcv_data]
        crypto_com_rsi = calculate_rsi(closes, period=14)
        print(f"✅ RSI calculado desde Crypto.com: {crypto_com_rsi}")
    else:
        print(f"⚠️  No hay suficientes datos OHLCV para calcular RSI")
    
    # Obtener datos del dashboard
    print("\n💾 Obteniendo datos del dashboard...")
    dashboard_data = get_dashboard_data(symbol)
    
    # Extraer precio del dashboard (prioridad: MarketPrice > WatchlistItem)
    dashboard_price = (
        dashboard_data["market_price"]["price"] or 
        dashboard_data["watchlist"]["price"]
    )
    
    # Extraer RSI del dashboard (prioridad: MarketData > WatchlistItem)
    dashboard_rsi = (
        dashboard_data["market_data"]["rsi"] or 
        dashboard_data["watchlist"]["rsi"]
    )
    
    print(f"✅ Precio desde dashboard: ${dashboard_price:,.2f}" if dashboard_price else "❌ No hay precio en dashboard")
    print(f"✅ RSI desde dashboard: {dashboard_rsi}" if dashboard_rsi else "❌ No hay RSI en dashboard")
    
    # Comparar
    print(f"\n{'='*80}")
    print("📊 COMPARACIÓN")
    print(f"{'='*80}\n")
    
    # Comparar precios
    if dashboard_price:
        price_diff = abs(crypto_com_price['price'] - dashboard_price)
        price_diff_pct = (price_diff / crypto_com_price['price']) * 100
        price_match = price_diff_pct < 0.1  # Menos del 0.1% de diferencia
        
        print(f"💰 PRECIO:")
        print(f"   Crypto.com:  ${crypto_com_price['price']:,.2f}")
        print(f"   Dashboard:   ${dashboard_price:,.2f}")
        print(f"   Diferencia:  ${price_diff:,.2f} ({price_diff_pct:.3f}%)")
        print(f"   Estado:      {'✅ COINCIDEN' if price_match else '❌ NO COINCIDEN'}")
    else:
        print(f"💰 PRECIO: ❌ No hay precio en dashboard para comparar")
    
    # Comparar RSI
    if crypto_com_rsi and dashboard_rsi:
        rsi_diff = abs(crypto_com_rsi - dashboard_rsi)
        rsi_match = rsi_diff < 2.0  # Menos de 2 puntos de diferencia
        
        print(f"\n📈 RSI:")
        print(f"   Crypto.com:  {crypto_com_rsi}")
        print(f"   Dashboard:   {dashboard_rsi}")
        print(f"   Diferencia:  {rsi_diff:.2f} puntos")
        print(f"   Estado:      {'✅ COINCIDEN' if rsi_match else '❌ NO COINCIDEN'}")
    else:
        print(f"\n📈 RSI: ⚠️  No se puede comparar (faltan datos)")
        if not crypto_com_rsi:
            print(f"   - No se pudo calcular RSI desde Crypto.com")
        if not dashboard_rsi:
            print(f"   - No hay RSI en dashboard")
    
    # Mostrar última actualización
    print(f"\n🕐 ÚLTIMA ACTUALIZACIÓN:")
    print(f"   Crypto.com:  {crypto_com_price['timestamp']}")
    if dashboard_data["market_price"]["updated_at"]:
        print(f"   Dashboard:   {dashboard_data['market_price']['updated_at']}")
    elif dashboard_data["watchlist"]["updated_at"]:
        print(f"   Dashboard:   {dashboard_data['watchlist']['updated_at']}")
    else:
        print(f"   Dashboard:   ❌ No disponible")
    
    print(f"\n{'='*80}\n")

def main():
    """Función principal"""
    symbols = ["BTC_USDT", "BTC_USD"]
    
    print("🔍 COMPARACIÓN DE DATOS: Crypto.com vs Dashboard")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    for symbol in symbols:
        compare_data(symbol)
    
    print("\n✅ Comparación completada")

if __name__ == "__main__":
    main()





