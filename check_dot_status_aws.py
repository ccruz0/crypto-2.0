#!/usr/bin/env python3
"""
Script para consultar el estado de DOT_USDT en el backend de AWS
Verifica alert_enabled, buy_alert_enabled, trade_enabled y otros flags
"""

import requests
import json
import sys

# URLs del backend
AWS_BACKEND_URL = "https://dashboard.hilovivo.com"
AWS_BACKEND_DIRECT = "http://54.254.150.31:8000"

SYMBOL = "DOT_USDT"

def check_symbol_status(symbol: str, base_url: str):
    """Consulta el estado de un símbolo en el backend"""
    print("=" * 70)
    print(f"🔍 CONSULTANDO ESTADO DE {symbol}")
    print("=" * 70)
    print(f"📍 Backend URL: {base_url}")
    print()
    
    try:
        # Endpoint para obtener información del símbolo
        url = f"{base_url}/api/dashboard/symbol/{symbol}"
        
        print(f"📡 Consultando: {url}")
        print()
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 404:
            print(f"❌ {symbol} no encontrado en la watchlist")
            return
        
        if response.status_code != 200:
            print(f"❌ Error HTTP {response.status_code}: {response.text}")
            return
        
        data = response.json()
        
        # Extraer información relevante
        print("1️⃣ CONFIGURACIÓN DE ALERTAS")
        print("-" * 70)
        
        alert_enabled = data.get("alert_enabled", False)
        buy_alert_enabled = data.get("buy_alert_enabled", False)
        sell_alert_enabled = data.get("sell_alert_enabled", False)
        trade_enabled = data.get("trade_enabled", False)
        trade_amount_usd = data.get("trade_amount_usd")
        
        print(f"   • alert_enabled (master switch): {'✅ YES' if alert_enabled else '❌ NO'}")
        print(f"   • buy_alert_enabled: {'✅ YES' if buy_alert_enabled else '❌ NO'}")
        print(f"   • sell_alert_enabled: {'✅ YES' if sell_alert_enabled else '❌ NO'}")
        print(f"   • trade_enabled: {'✅ YES' if trade_enabled else '❌ NO'}")
        print(f"   • trade_amount_usd: {trade_amount_usd if trade_amount_usd else '❌ NO CONFIGURADO'}")
        print()
        
        # Verificar flags críticos
        print("2️⃣ ANÁLISIS DE CONFIGURACIÓN")
        print("-" * 70)
        
        issues = []
        recommendations = []
        
        if not alert_enabled:
            issues.append("❌ alert_enabled = False (master switch deshabilitado)")
            recommendations.append("   → Habilitar alert_enabled para permitir alertas")
        
        if not buy_alert_enabled:
            issues.append("❌ buy_alert_enabled = False (alertas BUY deshabilitadas)")
            recommendations.append("   → Habilitar buy_alert_enabled para recibir alertas de compra")
        
        if not trade_enabled:
            issues.append("⚠️  trade_enabled = False (trading automático deshabilitado)")
            recommendations.append("   → Habilitar trade_enabled para crear órdenes automáticas")
        else:
            # Si trade_enabled está en YES, verificar que alert_enabled también lo esté
            if not alert_enabled:
                issues.append("⚠️  trade_enabled=YES pero alert_enabled=NO (inconsistencia)")
                recommendations.append("   → Cambiar trade_enabled a NO y luego a YES para auto-habilitar alert_enabled")
        
        if not trade_amount_usd or trade_amount_usd <= 0:
            issues.append("⚠️  trade_amount_usd no configurado")
            recommendations.append("   → Configurar trade_amount_usd para crear órdenes automáticas")
        
        # Verificar si ambos flags están habilitados (requisito para alertas BUY)
        if alert_enabled and buy_alert_enabled:
            print("   ✅ CONFIGURACIÓN CORRECTA: alert_enabled=YES y buy_alert_enabled=YES")
            print("      → Las alertas de compra deberían funcionar correctamente")
        else:
            print("   🚫 CONFIGURACIÓN INCOMPLETA:")
            for issue in issues:
                print(f"      {issue}")
        
        if recommendations:
            print()
            print("3️⃣ RECOMENDACIONES")
            print("-" * 70)
            for rec in recommendations:
                print(rec)
        
        # Información adicional
        print()
        print("4️⃣ INFORMACIÓN ADICIONAL")
        print("-" * 70)
        print(f"   • Symbol: {data.get('symbol', 'N/A')}")
        print(f"   • Exchange: {data.get('exchange', 'N/A')}")
        print(f"   • Price: ${data.get('price', 'N/A')}")
        print(f"   • RSI: {data.get('rsi', 'N/A')}")
        print(f"   • Preset: {data.get('preset', 'N/A')}")
        print(f"   • SL/TP Mode: {data.get('sl_tp_mode', 'N/A')}")
        print(f"   • Min Price Change %: {data.get('min_price_change_pct', 'N/A')}")
        print(f"   • Alert Cooldown (min): {data.get('alert_cooldown_minutes', 'N/A')}")
        
        print()
        print("=" * 70)
        print("✅ CONSULTA COMPLETADA")
        print("=" * 70)
        
    except requests.exceptions.Timeout:
        print(f"❌ Timeout al conectar con {base_url}")
        print("   Verifica que el backend esté accesible")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Error de conexión: {e}")
        print("   Verifica que el backend esté corriendo y accesible")
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Función principal"""
    # Intentar primero con el dominio público
    print("Intentando con dominio público (dashboard.hilovivo.com)...")
    print()
    try:
        check_symbol_status(SYMBOL, AWS_BACKEND_URL)
    except Exception as e:
        print(f"Error con dominio público: {e}")
        print()
        print("Intentando con IP directa (54.254.150.31:8000)...")
        print()
        check_symbol_status(SYMBOL, AWS_BACKEND_DIRECT)

if __name__ == "__main__":
    main()










