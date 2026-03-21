#!/usr/bin/env python3
"""Script para verificar el estado de alertas de ALGO usando la API"""
import requests
import json
import sys
import os

# Shared env (API_BASE_URL, AWS_BACKEND_URL) or local default 8002
API_BASE_URL = (
    os.getenv("API_BASE_URL")
    or os.getenv("AWS_BACKEND_URL")
    or "http://localhost:8002"
)
SYMBOL = "ALGO_USDT"

def main():
    print("=" * 80)
    print(f"🔍 Verificando estado de alertas para {SYMBOL}")
    print("=" * 80)
    print(f"📡 API Base: {API_BASE_URL}")
    print()
    
    # Construir URL del endpoint
    url = f"{API_BASE_URL.rstrip('/')}/api/dashboard/symbol/{SYMBOL}"
    
    print(f"📡 Consultando: {url}")
    print()
    
    try:
        # Hacer petición GET
        response = requests.get(url, timeout=10)
        
        if response.status_code == 404:
            print(f"❌ {SYMBOL} no encontrado en la watchlist")
            print()
            print("💡 Sugerencias:")
            print("   - Verifica que el símbolo esté agregado a la watchlist")
            print("   - Verifica que uses el símbolo correcto (ALGO_USDT, ALGO_USD, etc.)")
            return
        
        if response.status_code != 200:
            print(f"❌ Error al consultar la API: {response.status_code}")
            print(f"   Respuesta: {response.text[:200]}")
            return
        
        # Parsear respuesta JSON
        data = response.json()
        
        # Extraer información relevante
        symbol = data.get("symbol", SYMBOL)
        alert_enabled = data.get("alert_enabled", False)
        buy_alert_enabled = data.get("buy_alert_enabled", None)
        sell_alert_enabled = data.get("sell_alert_enabled", None)
        trade_enabled = data.get("trade_enabled", False)
        alert_cooldown_minutes = data.get("alert_cooldown_minutes", None)
        min_price_change_pct = data.get("min_price_change_pct", None)
        
        print("📊 Estado de Alertas:")
        print("-" * 80)
        print(f"  • Símbolo: {symbol}")
        print(f"  • alert_enabled (master switch): {alert_enabled} {'✅' if alert_enabled else '❌'}")
        print(f"  • buy_alert_enabled: {buy_alert_enabled} {'✅' if (buy_alert_enabled or (alert_enabled and buy_alert_enabled is None)) else '❌'}")
        print(f"  • sell_alert_enabled: {sell_alert_enabled} {'✅' if (sell_alert_enabled or (alert_enabled and sell_alert_enabled is None)) else '❌'}")
        print(f"  • trade_enabled: {trade_enabled} {'✅' if trade_enabled else '❌'}")
        print()
        
        # Configuración de throttling
        print("⏱️  Configuración de Throttling:")
        print("-" * 80)
        print(f"  • alert_cooldown_minutes: {alert_cooldown_minutes or 'default (5 min)'}")
        print(f"  • min_price_change_pct: {min_price_change_pct or 'default (1.0%)'}")
        print()
        
        # Determinar estado efectivo
        # Si alert_enabled=True y buy_alert_enabled es None, se considera habilitado
        buy_effectively_enabled = buy_alert_enabled if buy_alert_enabled is not None else (alert_enabled if alert_enabled else False)
        sell_effectively_enabled = sell_alert_enabled if sell_alert_enabled is not None else (alert_enabled if alert_enabled else False)
        
        print("=" * 80)
        print("✅ RESULTADO:")
        print("=" * 80)
        print()
        
        if alert_enabled:
            print("  • Master alert (alert_enabled): ✅ ENABLED")
            if buy_effectively_enabled:
                print("  • BUY alerts: ✅ ENABLED")
                print("     → Las alertas BUY se enviarán cuando se detecte una señal BUY")
            else:
                print("  • BUY alerts: ❌ DISABLED")
                print("     → Las alertas BUY NO se enviarán aunque se detecte una señal BUY")
            
            if sell_effectively_enabled:
                print("  • SELL alerts: ✅ ENABLED")
                print("     → Las alertas SELL se enviarán cuando se detecte una señal SELL")
            else:
                print("  • SELL alerts: ❌ DISABLED")
                print("     → Las alertas SELL NO se enviarán aunque se detecte una señal SELL")
        else:
            print("  • Master alert (alert_enabled): ❌ DISABLED")
            print("  • BUY alerts: ❌ DISABLED (master switch off)")
            print("  • SELL alerts: ❌ DISABLED (master switch off)")
            print()
            print("  ⚠️  IMPORTANTE: Todas las alertas están deshabilitadas porque")
            print("     alert_enabled=False. Activa el master switch en el dashboard")
            print("     para habilitar las alertas.")
        
        print()
        
        # Información adicional
        current_price = data.get("price")
        rsi = data.get("rsi")
        signals = data.get("signals", {})
        
        if current_price or rsi or signals:
            print("📊 Información Adicional:")
            print("-" * 80)
            if current_price:
                print(f"  • Precio actual: ${current_price:.4f}")
            if rsi:
                print(f"  • RSI: {rsi:.2f}")
            if signals:
                print(f"  • Señales manuales: {signals}")
            print()
        
        # Recomendaciones
        print("💡 Recomendaciones:")
        print("-" * 80)
        
        if not alert_enabled:
            print("  ⚠️  Activa 'alert_enabled' en el dashboard para habilitar las alertas")
        elif not buy_effectively_enabled and not sell_effectively_enabled:
            print("  ⚠️  Activa 'buy_alert_enabled' o 'sell_alert_enabled' según necesites")
        else:
            print("  ✅ Las alertas están configuradas correctamente")
            print("  📝 Recuerda que las alertas también requieren:")
            print("     - Que se detecte una señal BUY/SELL")
            print("     - Que se cumplan las condiciones de throttling (cooldown y cambio de precio)")
        
        print()
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Error de conexión: No se pudo conectar a {API_BASE_URL}")
        print()
        print("💡 Verifica que:")
        print("   - El servidor backend esté ejecutándose")
        print("   - La URL sea correcta (usa API_BASE_URL env var para cambiarla)")
        print("   - No haya problemas de red/firewall")
        print()
        print("   Ejemplo: API_BASE_URL=http://localhost:8002 python3 check_algo_api.py")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print(f"❌ Timeout: La petición tardó demasiado")
        print()
        print("💡 El servidor puede estar sobrecargado o lento")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()





