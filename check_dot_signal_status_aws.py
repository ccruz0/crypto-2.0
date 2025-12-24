#!/usr/bin/env python3
"""
Script para consultar el estado de señales y throttle de DOT_USDT en AWS
"""

import requests
import json
from datetime import datetime, timezone

AWS_BACKEND_URL = "https://dashboard.hilovivo.com"
SYMBOL = "DOT_USDT"

def check_signal_status(symbol: str):
    """Consulta el estado de señales y throttle"""
    print("=" * 70)
    print(f"🔍 ESTADO DE SEÑALES Y THROTTLE: {symbol}")
    print("=" * 70)
    print()
    
    try:
        # 1. Consultar señales actuales
        print("1️⃣ SEÑALES ACTUALES")
        print("-" * 70)
        signals_url = f"{AWS_BACKEND_URL}/api/signals?symbol={symbol}"
        print(f"📡 Consultando: {signals_url}")
        
        signals_data = {}
        response = requests.get(signals_url, timeout=10)
        if response.status_code == 200:
            signals_data = response.json()
            print(f"   • Señal BUY: {signals_data.get('buy_signal', 'N/A')}")
            print(f"   • Señal SELL: {signals_data.get('sell_signal', 'N/A')}")
            print(f"   • Estado: {signals_data.get('signal_state', 'N/A')}")
            print(f"   • Precio: ${signals_data.get('price', 'N/A')}")
            print(f"   • RSI: {signals_data.get('rsi', 'N/A')}")
            print()
        else:
            print(f"   ⚠️  Error al consultar señales: {response.status_code}")
            print(f"   → Respuesta: {response.text[:200]}")
            print()
        
        # 2. Consultar estado del throttle (si hay endpoint)
        print("2️⃣ INFORMACIÓN DEL WATCHLIST")
        print("-" * 70)
        watchlist_url = f"{AWS_BACKEND_URL}/api/dashboard/symbol/{symbol}"
        print(f"📡 Consultando: {watchlist_url}")
        
        response = requests.get(watchlist_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            print(f"   • alert_enabled: {'✅ YES' if data.get('alert_enabled') else '❌ NO'}")
            print(f"   • buy_alert_enabled: {'✅ YES' if data.get('buy_alert_enabled') else '❌ NO'}")
            print(f"   • trade_enabled: {'✅ YES' if data.get('trade_enabled') else '❌ NO'}")
            print(f"   • min_price_change_pct: {data.get('min_price_change_pct', 'N/A')}")
            print(f"   • alert_cooldown_minutes: {data.get('alert_cooldown_minutes', 'N/A')}")
            print()
            
            # Verificar si hay condiciones que bloqueen la alerta
            print("3️⃣ ANÁLISIS")
            print("-" * 70)
            
            if not data.get('alert_enabled'):
                print("   🚫 alert_enabled = NO → Las alertas están deshabilitadas")
            elif not data.get('buy_alert_enabled'):
                print("   🚫 buy_alert_enabled = NO → Las alertas BUY están deshabilitadas")
            else:
                print("   ✅ Flags de alerta están habilitados")
                
                # Verificar condiciones de señal
                if signals_data.get('buy_signal'):
                    print("   ✅ Señal BUY detectada")
                    print("   → La alerta debería enviarse si no hay throttle activo")
                else:
                    print("   ⚠️  Señal BUY NO detectada")
                    print("   → Verificar condiciones: RSI, MA, Volume, etc.")
            
            print()
            print("4️⃣ RECOMENDACIONES")
            print("-" * 70)
            
            if data.get('alert_enabled') and data.get('buy_alert_enabled'):
                if signals_data.get('buy_signal'):
                    print("   ✅ Configuración correcta y señal BUY presente")
                    print("   → Si no saltó la alerta, puede ser:")
                    print("      • Throttle/cooldown activo")
                    print("      • Cambio reciente que aún no se procesó")
                    print("      • Verificar logs del backend para más detalles")
                else:
                    print("   ⚠️  Configuración correcta pero señal BUY no presente")
                    print("   → Verificar condiciones técnicas (RSI, MA, Volume)")
            else:
                print("   🚫 Configuración incompleta")
                if not data.get('alert_enabled'):
                    print("   → Habilitar alert_enabled")
                if not data.get('buy_alert_enabled'):
                    print("   → Habilitar buy_alert_enabled")
        
        print()
        print("=" * 70)
        print("✅ CONSULTA COMPLETADA")
        print("=" * 70)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_signal_status(SYMBOL)

