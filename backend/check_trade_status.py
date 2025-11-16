#!/usr/bin/env python3
"""
Script para verificar el estado de trade_enabled usando la API del backend
"""
import requests
import json
import sys
import os

# Intentar AWS primero, luego localhost
AWS_BACKEND_URL = os.getenv("AWS_BACKEND_URL", "http://175.41.189.249:8002")
LOCAL_BACKEND_URL = "http://localhost:8002"
API_KEY = "demo-key"

def check_trade_status():
    """Verificar el estado de trade_enabled usando la API"""
    # Intentar AWS primero, luego localhost como fallback
    urls_to_try = [
        (AWS_BACKEND_URL, "AWS"),
        (LOCAL_BACKEND_URL, "Local")
    ]
    
    data = None
    connected_env = None
    
    for base_url, env_name in urls_to_try:
        api_url = f"{base_url}/api/dashboard"
        health_url = f"{base_url}/health"
        
        try:
            print(f"🔗 Intentando conectar al backend {env_name}...")
            print(f"   URL: {api_url}")
            
            # Primero verificar health
            health_response = requests.get(health_url, timeout=5)
            if health_response.status_code != 200:
                print(f"   ⚠️  Health check falló: {health_response.status_code}")
                continue
                
            print(f"   ✅ Health check OK")
            
            headers = {
                "x-api-key": API_KEY,
                "Content-Type": "application/json"
            }
            
            response = requests.get(api_url, headers=headers, timeout=30)
        
            if response.status_code != 200:
                print(f"   ❌ Error al conectar con el backend: {response.status_code}")
                print(f"   Respuesta: {response.text[:200]}")
                continue
            
            # Si llegamos aquí, la conexión fue exitosa
            print(f"   ✅ Conectado exitosamente al backend {env_name}\n")
            data = response.json()
            connected_env = env_name
            break
            
        except requests.exceptions.Timeout:
            print(f"   ⏱️  Timeout al conectar con {env_name}")
            continue
        except requests.exceptions.ConnectionError:
            print(f"   ❌ No se pudo conectar con {env_name}")
            continue
        except Exception as e:
            print(f"   ❌ Error con {env_name}: {e}")
            continue
    
    # Si llegamos aquí sin datos, ningún backend respondió
    if data is None:
        print(f"\n❌ No se pudo conectar a ningún backend")
        print(f"   Intentado:")
        print(f"   - AWS: {AWS_BACKEND_URL}")
        print(f"   - Local: {LOCAL_BACKEND_URL}")
        print(f"\n   Asegúrate de que el backend de AWS esté corriendo en el servidor")
        sys.exit(1)
    
    # Procesar los datos
    if not data:
        print("❌ No se encontraron monedas en la respuesta del backend")
        return
    
    print(f"📊 Encontradas {len(data)} monedas en el backend ({connected_env}):\n")
    print("=" * 120)
    print(f"{'Symbol':<15} {'Trade':<10} {'Amount USD':<12} {'Alert':<10} {'Exchange':<15}")
    print("=" * 120)
    
    trade_yes_count = 0
    trade_no_count = 0
    trade_yes_symbols = []
    
    for item in data:
        symbol = item.get("symbol", "N/A")
        trade_enabled = item.get("trade_enabled", False)
        amount = item.get("trade_amount_usd")
        alert_enabled = item.get("alert_enabled", False)
        exchange = item.get("exchange", "N/A")
        
        trade_status = "✅ YES" if trade_enabled else "❌ NO"
        amount_str = f"${amount:,.2f}" if amount else "N/A"
        alert_status = "✅ YES" if alert_enabled else "❌ NO"
        
        print(f"{symbol:<15} {trade_status:<10} {amount_str:<12} {alert_status:<10} {exchange:<15}")
        
        if trade_enabled:
            trade_yes_count += 1
            trade_yes_symbols.append(symbol)
        else:
            trade_no_count += 1
    
    print("=" * 120)
    print(f"\n📈 Resumen:")
    print(f"   ✅ Trade YES: {trade_yes_count} monedas")
    print(f"   ❌ Trade NO:  {trade_no_count} monedas")
    print(f"   📊 Total:     {len(data)} monedas")
    
    # Verificar específicamente las monedas que aparecen en el dashboard
    dashboard_symbols = ["ETH_USDT", "SOL_USDT", "LDO_USD", "BTC_USD"]
    print(f"\n🔍 Verificación de monedas del dashboard:")
    print("=" * 120)
    
    found_symbols = {item.get("symbol"): item for item in data}
    
    for symbol in dashboard_symbols:
        if symbol in found_symbols:
            item = found_symbols[symbol]
            trade_enabled = item.get("trade_enabled", False)
            amount = item.get("trade_amount_usd")
            alert_enabled = item.get("alert_enabled", False)
            
            trade_status = "✅ YES" if trade_enabled else "❌ NO"
            amount_str = f"${amount:,.2f}" if amount else "N/A"
            alert_status = "✅ YES" if alert_enabled else "❌ NO"
            
            status_icon = "✅" if trade_enabled else "❌"
            print(f"   {status_icon} {symbol:<15} Trade: {trade_status:<10} Amount: {amount_str:<12} Alert: {alert_status}")
        else:
            print(f"   ⚠️  {symbol:<15} No encontrada en el backend")
    
    print("=" * 120)
    
    # Comparación con lo que muestra el dashboard
    print(f"\n📋 Monedas con Trade YES (según backend):")
    if trade_yes_symbols:
        for symbol in sorted(trade_yes_symbols):
            print(f"   ✅ {symbol}")
    else:
        print("   ❌ Ninguna moneda tiene Trade YES")
    
    print(f"\n✅ Verificación completada")
    print(f"\n💡 Nota: Si el dashboard muestra Trade YES pero aquí aparece NO,")
    print(f"   significa que el cambio no se guardó correctamente en la base de datos.")

if __name__ == "__main__":
    try:
        check_trade_status()
    except Exception as e:
        print(f"\n❌ Error al verificar el estado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
