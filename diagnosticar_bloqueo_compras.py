#!/usr/bin/env python3
"""
Diagnosticar qué está bloqueando las compras
"""

import requests
import json

AWS_BACKEND_URL = "https://dashboard.hilovivo.com"

def diagnosticar_bloqueo(symbol):
    print("=" * 70)
    print(f"🔍 DIAGNÓSTICO DE BLOQUEO DE COMPRAS: {symbol}")
    print("=" * 70)
    print()
    
    try:
        # 1. Verificar configuración
        print("1️⃣ CONFIGURACIÓN DEL SÍMBOLO")
        print("-" * 70)
        response = requests.get(f"{AWS_BACKEND_URL}/api/dashboard/symbol/{symbol}", timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            alert_enabled = data.get('alert_enabled', False)
            buy_alert_enabled = data.get('buy_alert_enabled', False)
            trade_enabled = data.get('trade_enabled', False)
            
            print(f"   • alert_enabled: {'✅ YES' if alert_enabled else '❌ NO'}")
            print(f"   • buy_alert_enabled: {'✅ YES' if buy_alert_enabled else '❌ NO'}")
            print(f"   • trade_enabled: {'✅ YES' if trade_enabled else '❌ NO'} ← CRÍTICO para crear órdenes")
            print()
            
            if not trade_enabled:
                print("   🚫 BLOQUEO ENCONTRADO: trade_enabled=NO")
                print("   → Las órdenes NO se crearán aunque haya señal BUY")
                print("   → SOLUCIÓN: Cambia trade_enabled a YES")
                return
            
            if not alert_enabled:
                print("   ⚠️  alert_enabled=NO (las alertas no se enviarán)")
            
            if not buy_alert_enabled:
                print("   ⚠️  buy_alert_enabled=NO (las alertas BUY no se enviarán)")
        else:
            print(f"   ❌ Error: {response.status_code}")
            return
        
        # 2. Verificar señales
        print("2️⃣ SEÑALES")
        print("-" * 70)
        response = requests.get(
            f"{AWS_BACKEND_URL}/api/signals",
            params={"symbol": symbol, "exchange": "CRYPTO_COM"},
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            buy_signal = data.get("buy_signal", False)
            strategy = data.get("strategy", {})
            decision = strategy.get("decision", "WAIT") if strategy else "WAIT"
            index = strategy.get("index") if strategy else None
            
            print(f"   • buy_signal: {'✅ True' if buy_signal else '❌ False'}")
            print(f"   • strategy.decision: {decision}")
            print(f"   • strategy.index: {index}%")
            print()
            
            if decision != "BUY":
                print("   ⚠️  No hay señal BUY activa")
                print("   → Las órdenes solo se crean cuando hay señal BUY")
                return
        else:
            print(f"   ❌ Error: {response.status_code}")
            return
        
        # 3. Verificar órdenes abiertas
        print("3️⃣ ÓRDENES ABIERTAS")
        print("-" * 70)
        response = requests.get(f"{AWS_BACKEND_URL}/api/orders/open", timeout=15)
        if response.status_code == 200:
            orders = response.json()
            buy_orders = [o for o in orders if o.get('side', '').upper() == 'BUY']
            symbol_buy_orders = [o for o in buy_orders if symbol in o.get('symbol', '')]
            
            print(f"   • Total órdenes BUY abiertas: {len(buy_orders)}")
            print(f"   • Órdenes BUY para {symbol}: {len(symbol_buy_orders)}")
            print()
            
            if len(symbol_buy_orders) >= 3:
                print("   🚫 BLOQUEO ENCONTRADO: Máximo de 3 órdenes abiertas por símbolo")
                print("   → El sistema permite máximo 3 órdenes abiertas por símbolo")
                print("   → SOLUCIÓN: Espera a que se ejecuten o cancela algunas órdenes")
                return
            
            if symbol_buy_orders:
                print("   ℹ️  Órdenes abiertas encontradas:")
                for order in symbol_buy_orders[:3]:
                    order_id = order.get('order_id', 'N/A')
                    price = order.get('price', 'N/A')
                    status = order.get('status', 'N/A')
                    print(f"      • {order_id}: ${price} ({status})")
                print()
        else:
            print(f"   ⚠️  No se pudo verificar órdenes: {response.status_code}")
        
        # 4. Resumen
        print("4️⃣ RESUMEN")
        print("-" * 70)
        print("   ✅ Configuración correcta")
        print("   ✅ Señal BUY activa")
        print("   ✅ No hay bloqueos obvios")
        print()
        print("   💡 POSIBLES BLOQUEOS:")
        print("   1. Cooldown: Hay una orden reciente (< 5 minutos)")
        print("   2. Cambio de precio: Requiere 1% de cambio desde última orden")
        print("   3. Portfolio limit: Valor del portfolio > 3x trade_amount_usd")
        print("   4. Locks: Hay un lock activo de creación de órdenes")
        print()
        print("   🔍 Revisa los logs del backend para más detalles:")
        print("   docker compose --profile aws logs backend | grep -E '(BLOCKED|should_create_order)'")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC_USDT"
    diagnosticar_bloqueo(symbol)









