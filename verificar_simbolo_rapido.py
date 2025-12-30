#!/usr/bin/env python3
"""
Verificar rápidamente el estado de un símbolo específico
"""

import requests
import sys

AWS_BACKEND_URL = "https://dashboard.hilovivo.com"

def verificar_simbolo(symbol):
    print(f"🔍 Verificando {symbol}...")
    print("-" * 70)
    
    try:
        # Verificar configuración
        response = requests.get(
            f"{AWS_BACKEND_URL}/api/dashboard/symbol/{symbol}",
            timeout=15
        )
        
        if response.status_code != 200:
            print(f"❌ Error: {response.status_code}")
            return
        
        data = response.json()
        
        alert_enabled = data.get('alert_enabled', False)
        buy_alert_enabled = data.get('buy_alert_enabled', False)
        trade_enabled = data.get('trade_enabled', False)
        
        print(f"📊 Configuración:")
        print(f"   • alert_enabled: {'✅ YES' if alert_enabled else '❌ NO'}")
        print(f"   • buy_alert_enabled: {'✅ YES' if buy_alert_enabled else '❌ NO'}")
        print(f"   • trade_enabled: {'✅ YES' if trade_enabled else '❌ NO'}")
        print()
        
        # Verificar si todos los flags están OK
        if trade_enabled:
            if alert_enabled and buy_alert_enabled:
                print("✅ Todos los flags están correctos")
                print("   → Las alertas deberían funcionar")
            else:
                print("⚠️  PROBLEMA: trade_enabled=YES pero faltan flags")
                if not alert_enabled:
                    print("   → alert_enabled debería ser YES")
                if not buy_alert_enabled:
                    print("   → buy_alert_enabled debería ser YES")
                print()
                print("💡 SOLUCIÓN:")
                print("   Cambia trade_enabled a NO y luego a YES de nuevo")
                print("   El fix debería habilitarlos automáticamente")
        else:
            print("ℹ️  trade_enabled=NO (no se esperan alertas)")
        
        print()
        
        # Verificar señales
        print("📊 Señales:")
        try:
            signals_response = requests.get(
                f"{AWS_BACKEND_URL}/api/signals",
                params={"symbol": symbol, "exchange": "CRYPTO_COM"},
                timeout=15
            )
            
            if signals_response.status_code == 200:
                signals_data = signals_response.json()
                strategy = signals_data.get("strategy", {})
                decision = strategy.get("decision", "WAIT") if strategy else "WAIT"
                index = strategy.get("index") if strategy else None
                
                print(f"   • decision: {decision}")
                print(f"   • index: {index}%")
                
                if decision == "BUY" and alert_enabled and buy_alert_enabled:
                    print()
                    print("🟢 BUY detectado y flags correctos")
                    print("   → La alerta debería saltar en el próximo ciclo (30 seg)")
                elif decision == "BUY":
                    print()
                    print("⚠️  BUY detectado pero flags incorrectos")
                    print("   → La alerta NO saltará hasta que se corrijan los flags")
                else:
                    print()
                    print(f"ℹ️  No hay señal BUY (decision={decision})")
            else:
                print(f"   ⚠️  No se pudo obtener señales: {signals_response.status_code}")
        except Exception as e:
            print(f"   ⚠️  Error al obtener señales: {e}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        symbols = sys.argv[1:]
    else:
        # Símbolos comunes para verificar
        symbols = ["BTC_USDT", "DOT_USDT", "ETH_USDT"]
    
    print("=" * 70)
    print("🔍 VERIFICACIÓN RÁPIDA DE SÍMBOLOS")
    print("=" * 70)
    print()
    
    for symbol in symbols:
        verificar_simbolo(symbol)
        print()










