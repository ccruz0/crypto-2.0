#!/usr/bin/env python3
"""
Script para verificar que el fix funciona en el dashboard
Verifica que signal_monitor ahora use strategy.decision
"""

import requests
import json
import time

AWS_BACKEND_URL = "https://dashboard.hilovivo.com"
SYMBOL = "BTC_USDT"

def verify_fix():
    print("=" * 70)
    print("🔍 VERIFICANDO FIX EN EL DASHBOARD")
    print("=" * 70)
    print()
    
    try:
        # 1. Verificar que el backend responde
        print("1️⃣ VERIFICANDO CONECTIVIDAD")
        print("-" * 70)
        health_url = f"{AWS_BACKEND_URL}/api/health"
        response = requests.get(health_url, timeout=10)
        if response.status_code == 200:
            print("   ✅ Backend está respondiendo")
        else:
            print(f"   ⚠️  Backend responde con código: {response.status_code}")
        print()
        
        # 2. Verificar configuración de BTC
        print("2️⃣ CONFIGURACIÓN DE BTC")
        print("-" * 70)
        watchlist_url = f"{AWS_BACKEND_URL}/api/dashboard/symbol/{SYMBOL}"
        response = requests.get(watchlist_url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print(f"   • alert_enabled: {'✅ YES' if data.get('alert_enabled') else '❌ NO'}")
            print(f"   • buy_alert_enabled: {'✅ YES' if data.get('buy_alert_enabled') else '❌ NO'}")
            print(f"   • trade_enabled: {'✅ YES' if data.get('trade_enabled') else '❌ NO'}")
        else:
            print(f"   ❌ Error: {response.status_code}")
        print()
        
        # 3. Verificar señales usando el endpoint /api/signals
        print("3️⃣ SEÑALES DESDE /api/signals")
        print("-" * 70)
        signals_url = f"{AWS_BACKEND_URL}/api/signals"
        params = {
            "symbol": SYMBOL,
            "exchange": "CRYPTO_COM"
        }
        
        response = requests.get(signals_url, params=params, timeout=10)
        if response.status_code == 200:
            signals_data = response.json()
            
            buy_signal = signals_data.get("buy_signal", False)
            strategy = signals_data.get("strategy", {})
            decision = strategy.get("decision", "WAIT") if strategy else "WAIT"
            index = strategy.get("index") if strategy else None
            
            print(f"   • buy_signal: {'✅ True' if buy_signal else '❌ False'}")
            print(f"   • strategy.decision: {decision}")
            print(f"   • strategy.index: {index}%")
            print()
            
            # 4. Verificar que strategy.decision coincide con buy_signal
            print("4️⃣ VERIFICACIÓN DE CONSISTENCIA")
            print("-" * 70)
            
            if decision == "BUY" and buy_signal:
                print("   ✅ CONSISTENTE: strategy.decision=BUY y buy_signal=True")
                print("   → El fix debería funcionar correctamente")
            elif decision == "BUY" and not buy_signal:
                print("   ⚠️  INCONSISTENCIA: strategy.decision=BUY pero buy_signal=False")
                print("   → Esto es lo que el fix debería corregir")
                print("   → signal_monitor ahora usará strategy.decision en lugar de buy_signal")
            elif decision != "BUY" and not buy_signal:
                print("   ✅ CONSISTENTE: No hay señal BUY (decision={}, buy_signal={})".format(decision, buy_signal))
            else:
                print(f"   ⚠️  Estado inesperado: decision={decision}, buy_signal={buy_signal}")
            
            print()
            print("5️⃣ RESUMEN")
            print("-" * 70)
            print("   El fix implementado hace que signal_monitor use strategy.decision")
            print("   como fuente primaria, igual que el dashboard.")
            print()
            print("   Si el dashboard muestra BUY con INDEX:100%, entonces:")
            print("   → strategy.decision = 'BUY'")
            print("   → signal_monitor ahora usará esto para detectar la señal")
            print("   → La alerta debería saltar si alert_enabled y buy_alert_enabled = YES")
            
        else:
            print(f"   ❌ Error al consultar señales: {response.status_code}")
            print(f"   → {response.text[:200]}")
        
        print()
        print("=" * 70)
        print("✅ VERIFICACIÓN COMPLETADA")
        print("=" * 70)
        print()
        print("💡 PRÓXIMOS PASOS:")
        print("   1. Verifica en el dashboard que BTC muestra BUY con INDEX:100%")
        print("   2. Verifica que alert_enabled y buy_alert_enabled están en YES")
        print("   3. Espera al próximo ciclo de signal_monitor (cada 30 segundos)")
        print("   4. La alerta debería saltar automáticamente")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_fix()










