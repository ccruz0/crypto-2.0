#!/usr/bin/env python3
"""
Verificar el estado de las alertas para símbolos con trade_enabled=YES
"""

import requests
import json

AWS_BACKEND_URL = "https://dashboard.hilovivo.com"

def verificar_alertas():
    print("=" * 70)
    print("🔍 VERIFICANDO ALERTAS ACTIVAS")
    print("=" * 70)
    print()
    
    try:
        # Obtener todos los símbolos del dashboard
        print("📊 Obteniendo lista de símbolos...")
        response = requests.get(f"{AWS_BACKEND_URL}/api/dashboard", timeout=10)
        
        if response.status_code != 200:
            print(f"❌ Error al obtener dashboard: {response.status_code}")
            return
        
        watchlist = response.json()
        if not isinstance(watchlist, list):
            print("❌ Respuesta inesperada del dashboard")
            return
        
        # Filtrar símbolos con trade_enabled=YES
        symbols_with_trade = []
        for item in watchlist:
            symbol = item.get('symbol', '')
            trade_enabled = item.get('trade_enabled', False)
            alert_enabled = item.get('alert_enabled', False)
            buy_alert_enabled = item.get('buy_alert_enabled', False)
            
            if trade_enabled:
                symbols_with_trade.append({
                    'symbol': symbol,
                    'alert_enabled': alert_enabled,
                    'buy_alert_enabled': buy_alert_enabled,
                    'trade_enabled': trade_enabled
                })
        
        print(f"✅ Encontrados {len(symbols_with_trade)} símbolos con trade_enabled=YES")
        print()
        
        if not symbols_with_trade:
            print("⚠️  No hay símbolos con trade_enabled=YES")
            return
        
        # Verificar cada símbolo
        print("=" * 70)
        print("📋 ESTADO DE CADA SÍMBOLO")
        print("=" * 70)
        print()
        
        problemas = []
        correctos = []
        
        for item in symbols_with_trade[:10]:  # Limitar a 10 para no saturar
            symbol = item['symbol']
            print(f"🔍 {symbol}:")
            
            # Verificar flags
            flags_ok = True
            if not item['alert_enabled']:
                print(f"   ❌ alert_enabled: NO (debería ser YES)")
                flags_ok = False
            else:
                print(f"   ✅ alert_enabled: YES")
            
            if not item['buy_alert_enabled']:
                print(f"   ❌ buy_alert_enabled: NO (debería ser YES)")
                flags_ok = False
            else:
                print(f"   ✅ buy_alert_enabled: YES")
            
            if not item['trade_enabled']:
                print(f"   ❌ trade_enabled: NO")
                flags_ok = False
            else:
                print(f"   ✅ trade_enabled: YES")
            
            # Verificar señales
            try:
                signals_response = requests.get(
                    f"{AWS_BACKEND_URL}/api/signals",
                    params={"symbol": symbol, "exchange": "CRYPTO_COM"},
                    timeout=10
                )
                
                if signals_response.status_code == 200:
                    signals_data = signals_response.json()
                    strategy = signals_data.get("strategy", {})
                    decision = strategy.get("decision", "WAIT") if strategy else "WAIT"
                    index = strategy.get("index") if strategy else None
                    buy_signal = signals_data.get("buy_signal", False)
                    
                    print(f"   📊 Señal: {decision} (INDEX: {index}%)")
                    
                    if decision == "BUY" and flags_ok:
                        print(f"   🟢 BUY detectado - Alerta debería saltar en próximo ciclo")
                        correctos.append(symbol)
                    elif decision == "BUY" and not flags_ok:
                        print(f"   ⚠️  BUY detectado pero flags incorrectos - Alerta NO saltará")
                        problemas.append({
                            'symbol': symbol,
                            'issue': 'BUY detectado pero flags incorrectos',
                            'flags': item
                        })
                    elif decision != "BUY":
                        print(f"   ⏸️  No hay señal BUY (decision={decision})")
                else:
                    print(f"   ⚠️  No se pudo obtener señales: {signals_response.status_code}")
            except Exception as e:
                print(f"   ⚠️  Error al obtener señales: {e}")
            
            print()
        
        # Resumen
        print("=" * 70)
        print("📊 RESUMEN")
        print("=" * 70)
        print()
        
        if problemas:
            print(f"⚠️  {len(problemas)} símbolo(s) con problemas:")
            for p in problemas:
                print(f"   • {p['symbol']}: {p['issue']}")
            print()
            print("💡 SOLUCIÓN:")
            print("   Si alert_enabled o buy_alert_enabled están en NO,")
            print("   cambia trade_enabled a NO y luego a YES de nuevo.")
            print("   El fix debería habilitarlos automáticamente.")
        else:
            print("✅ Todos los símbolos tienen los flags correctos")
        
        if correctos:
            print()
            print(f"🟢 {len(correctos)} símbolo(s) listo(s) para alertas BUY:")
            for s in correctos:
                print(f"   • {s}")
            print()
            print("💡 Espera 30 segundos (próximo ciclo de signal_monitor)")
            print("   Las alertas deberían saltar automáticamente")
        
        print()
        print("=" * 70)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verificar_alertas()















