#!/usr/bin/env python3
"""
Verificar qué devuelve getTopCoins para BTC y su strategy decision
"""

import requests
import json

AWS_BACKEND_URL = "https://dashboard.hilovivo.com"
SYMBOL = "BTC_USDT"

def check():
    print("=" * 70)
    print(f"🔍 VERIFICANDO getTopCoins() para {SYMBOL}")
    print("=" * 70)
    print()
    
    try:
        # Consultar getTopCoins
        url = f"{AWS_BACKEND_URL}/api/dashboard"
        print(f"📡 Consultando: {url}")
        print()
        
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            print(f"❌ Error: {response.status_code}")
            print(f"   → {response.text[:200]}")
            return
        
        data = response.json()
        
        # El endpoint puede devolver una lista o un objeto
        if isinstance(data, list):
            top_coins = data
        else:
            top_coins = data.get("fast_signals", []) + data.get("slow_signals", [])
        
        btc_coin = None
        for coin in top_coins:
            if coin.get("instrument_name") == SYMBOL:
                btc_coin = coin
                break
        
        if not btc_coin:
            print(f"❌ {SYMBOL} no encontrado en top coins")
            return
        
        print("1️⃣ DATOS DE BTC DESDE getTopCoins()")
        print("-" * 70)
        print(f"   • Symbol: {btc_coin.get('instrument_name')}")
        print(f"   • Price: ${btc_coin.get('current_price', 0):,.2f}")
        print(f"   • RSI: {btc_coin.get('rsi', 'N/A')}")
        print(f"   • EMA10: ${btc_coin.get('ema10', 0):,.2f}" if btc_coin.get('ema10') else "   • EMA10: N/A")
        print(f"   • MA50: ${btc_coin.get('ma50', 0):,.2f}" if btc_coin.get('ma50') else "   • MA50: N/A")
        print(f"   • MA200: ${btc_coin.get('ma200', 0):,.2f}" if btc_coin.get('ma200') else "   • MA200: N/A")
        print(f"   • Volume Ratio: {btc_coin.get('volume_ratio', 'N/A')}")
        print()
        
        # Verificar strategy
        strategy = btc_coin.get("strategy")
        if strategy:
            print("2️⃣ STRATEGY DECISION (lo que muestra el frontend)")
            print("-" * 70)
            print(f"   • Decision: {strategy.get('decision', 'N/A')}")
            print(f"   • Index: {strategy.get('index', 'N/A')}")
            print(f"   • Reasons: {json.dumps(strategy.get('reasons', {}), indent=6)}")
            print()
            
            decision = strategy.get('decision')
            index = strategy.get('index')
            
            print("3️⃣ ANÁLISIS")
            print("-" * 70)
            if decision == 'BUY' and index == 100:
                print("   ✅ El frontend muestra BUY con INDEX:100%")
                print("   → Esto significa que el backend calculó que TODAS las condiciones se cumplen")
                print("   → Pero /api/signals reporta buy_signal = False")
                print()
                print("   🔍 POSIBLE CAUSA:")
                print("      • Diferentes endpoints usan diferentes lógicas de cálculo")
                print("      • O hay un problema de sincronización entre endpoints")
                print("      • O el signal_monitor usa una lógica diferente a getTopCoins")
            else:
                print(f"   ⚠️  Decision: {decision}, Index: {index}")
        else:
            print("   ⚠️  No hay strategy data en el coin")
        
        print()
        print("=" * 70)
        print("✅ VERIFICACIÓN COMPLETADA")
        print("=" * 70)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check()

