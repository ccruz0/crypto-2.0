#!/usr/bin/env python3
"""
Script para probar la conexión del dashboard con datos reales
"""

import requests
import json
from datetime import datetime

def test_dashboard_connection():
    """Probar la conexión del dashboard"""
    try:
        print("🔍 Probando conexión al dashboard...")
        
        # Test 1: Servidor de datos reales
        print("\n1️⃣ Probando servidor de datos reales...")
        response = requests.get("http://localhost:8001/api/crypto-data", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Servidor de datos: {data.get('count', 0)} cryptos disponibles")
            print(f"📊 Ejemplo: {data.get('data', [])[:2]}")
        else:
            print(f"❌ Error servidor de datos: {response.status_code}")
            return False
        
        # Test 2: Frontend
        print("\n2️⃣ Probando frontend...")
        response = requests.get("http://localhost:3000", timeout=10)
        if response.status_code == 200:
            print("✅ Frontend disponible")
        else:
            print(f"❌ Error frontend: {response.status_code}")
            return False
        
        # Test 3: API del frontend
        print("\n3️⃣ Probando API del frontend...")
        try:
            # Simular la llamada que hace el frontend
            response = requests.get("http://localhost:8001/api/crypto-data", 
                                 headers={'X-API-Key': 'demo-key'}, timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ API del frontend: {len(data.get('data', []))} cryptos")
                return True
            else:
                print(f"❌ Error API del frontend: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Error en API del frontend: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Error general: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Probando conexión del dashboard con datos reales...")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    success = test_dashboard_connection()
    
    if success:
        print("\n✅ ¡Todo funcionando! El dashboard debería mostrar datos reales")
        print("🌐 Abre http://localhost:3000 en tu navegador")
    else:
        print("\n❌ Hay problemas con la conexión")

