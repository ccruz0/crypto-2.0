#!/usr/bin/env python3
"""
Script para probar el servidor multi-exchange
"""

import requests
import json
from datetime import datetime

def test_multi_exchange():
    """Probar el servidor multi-exchange"""
    try:
        print("🔍 Probando servidor multi-exchange...")
        
        # Test 1: Endpoint principal
        response = requests.get("http://localhost:8001/api/crypto-data", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Endpoint principal: {data.get('count', 0)} cryptos")
            print(f"📊 Fuentes: {', '.join(data.get('sources', []))}")
            
            # Mostrar primeros 5 cryptos
            print("\n📈 Top 5 Cryptos (Datos Agregados):")
            print("-" * 80)
            for i, crypto in enumerate(data.get('data', [])[:5]):
                sources = ', '.join(crypto.get('sources', []))
                print(f"{i+1:2d}. {crypto['symbol']:8} | ${crypto['price']:>12,.2f} | {crypto['change_percent']:>6.2f}% | Fuentes: {sources}")
            
            return True
        else:
            print(f"❌ Error endpoint principal: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_all_endpoints():
    """Probar todos los endpoints"""
    endpoints = [
        "/api/crypto-data",
        "/api/account/balance", 
        "/api/orders/open",
        "/api/orders/history",
        "/api/instruments"
    ]
    
    print("🔍 Probando todos los endpoints...")
    for endpoint in endpoints:
        try:
            response = requests.get(f"http://localhost:8001{endpoint}", timeout=5)
            if response.status_code == 200:
                print(f"✅ {endpoint}")
            else:
                print(f"❌ {endpoint}: {response.status_code}")
        except Exception as e:
            print(f"❌ {endpoint}: {e}")

if __name__ == "__main__":
    print("🚀 Probando servidor multi-exchange...")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Test principal
    success = test_multi_exchange()
    
    if success:
        print("\n🔍 Probando todos los endpoints...")
        test_all_endpoints()
        
        print("\n✅ ¡Servidor multi-exchange funcionando correctamente!")
        print("🌐 El dashboard debería mostrar datos de múltiples fuentes")
    else:
        print("\n❌ Hay problemas con el servidor multi-exchange")

