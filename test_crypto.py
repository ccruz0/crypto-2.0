#!/usr/bin/env python3
"""
Script para probar la conexión a Crypto.com y obtener datos reales
"""

import requests
import json
from datetime import datetime

def get_crypto_data():
    """Obtener datos reales de Crypto.com"""
    try:
        print("🔍 Conectando a Crypto.com API...")
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        print("✅ Conexión exitosa!")
        print(f"📊 Datos obtenidos: {len(result.get('result', {}).get('data', []))} instrumentos")
        
        # Procesar datos
        crypto_data = []
        if "result" in result and "data" in result["result"]:
            print(f"🔍 Procesando {len(result['result']['data'])} instrumentos...")
            for i, ticker in enumerate(result["result"]["data"][:20]):  # Primeros 20
                instrument_name = ticker.get("i", "")
                last_price = float(ticker.get("a", 0))
                volume_24h = float(ticker.get("v", 0))
                price_change_24h = float(ticker.get("c", 0))
                
                print(f"  {i+1:2d}. {instrument_name} - Price: ${last_price}")
                
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
        
        print("\n📈 Top 10 Cryptos (Datos Reales):")
        print("-" * 60)
        for crypto in crypto_data:
            print(f"{crypto['symbol']:8} | ${crypto['price']:>12,.2f} | {crypto['change_percent']:>6.2f}% | Vol: ${crypto['volume_24h']:>10,.0f}")
        
        return crypto_data
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return []

if __name__ == "__main__":
    print("🚀 Obteniendo datos reales de Crypto.com...")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    data = get_crypto_data()
    
    if data:
        print(f"\n✅ ¡Éxito! Se obtuvieron {len(data)} cryptos con datos reales")
    else:
        print("\n❌ No se pudieron obtener datos")
