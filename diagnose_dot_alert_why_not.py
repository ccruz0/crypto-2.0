#!/usr/bin/env python3
"""
Diagnóstico completo: ¿Por qué no salta la alerta de compra para DOT?
Verifica todas las condiciones: flags, señales, throttle, condiciones técnicas
"""

import requests
import json
from datetime import datetime

AWS_BACKEND_URL = "https://dashboard.hilovivo.com"
SYMBOL = "DOT_USDT"

def diagnose():
    print("=" * 70)
    print(f"🔍 DIAGNÓSTICO COMPLETO: ¿Por qué no salta la alerta para {SYMBOL}?")
    print("=" * 70)
    print()
    
    try:
        # 1. Verificar configuración del watchlist
        print("1️⃣ CONFIGURACIÓN DEL WATCHLIST")
        print("-" * 70)
        watchlist_url = f"{AWS_BACKEND_URL}/api/dashboard/symbol/{SYMBOL}"
        response = requests.get(watchlist_url, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ Error al consultar watchlist: {response.status_code}")
            return
        
        watchlist_data = response.json()
        
        alert_enabled = watchlist_data.get("alert_enabled", False)
        buy_alert_enabled = watchlist_data.get("buy_alert_enabled", False)
        trade_enabled = watchlist_data.get("trade_enabled", False)
        price = watchlist_data.get("price")
        rsi = watchlist_data.get("rsi")
        ema10 = watchlist_data.get("ema10")
        ma50 = watchlist_data.get("ma50")
        ma200 = watchlist_data.get("ma200")
        volume_ratio = watchlist_data.get("volume_ratio")
        preset = watchlist_data.get("preset", "swing")
        sl_tp_mode = watchlist_data.get("sl_tp_mode", "conservative")
        
        print(f"   • alert_enabled: {'✅ YES' if alert_enabled else '❌ NO'}")
        print(f"   • buy_alert_enabled: {'✅ YES' if buy_alert_enabled else '❌ NO'}")
        print(f"   • trade_enabled: {'✅ YES' if trade_enabled else '❌ NO'}")
        print(f"   • Preset: {preset}")
        print(f"   • SL/TP Mode: {sl_tp_mode}")
        print()
        
        # 2. Verificar condiciones técnicas
        print("2️⃣ CONDICIONES TÉCNICAS ACTUALES")
        print("-" * 70)
        print(f"   • Precio: ${price}")
        print(f"   • RSI: {rsi}")
        print(f"   • EMA10: ${ema10 if ema10 else 'N/A'}")
        print(f"   • MA50: ${ma50 if ma50 else 'N/A'}")
        print(f"   • MA200: ${ma200 if ma200 else 'N/A'}")
        print(f"   • Volume Ratio: {volume_ratio if volume_ratio else 'N/A'}")
        print()
        
        # 3. Verificar señales usando el endpoint correcto
        print("3️⃣ ESTADO DE SEÑALES")
        print("-" * 70)
        
        # Intentar con el endpoint que requiere exchange
        signals_url = f"{AWS_BACKEND_URL}/api/signals"
        params = {
            "symbol": SYMBOL,
            "exchange": "CRYPTO_COM"  # Basado en el watchlist
        }
        
        response = requests.get(signals_url, params=params, timeout=10)
        if response.status_code == 200:
            signals_data = response.json()
            buy_signal = signals_data.get("buy_signal", False)
            sell_signal = signals_data.get("sell_signal", False)
            signal_state = signals_data.get("signal_state", "WAIT")
            
            print(f"   • Señal BUY: {'✅ SÍ' if buy_signal else '❌ NO'}")
            print(f"   • Señal SELL: {'✅ SÍ' if sell_signal else '❌ NO'}")
            print(f"   • Estado: {signal_state}")
            
            # Mostrar razones si están disponibles
            if "reasons" in signals_data:
                print(f"   • Razones: {', '.join(signals_data.get('reasons', []))}")
            
            print()
            
            # 4. Análisis de por qué no salta
            print("4️⃣ ANÁLISIS: ¿POR QUÉ NO SALTA LA ALERTA?")
            print("-" * 70)
            
            issues = []
            
            # Verificar flags
            if not alert_enabled:
                issues.append("❌ alert_enabled = NO (master switch deshabilitado)")
            if not buy_alert_enabled:
                issues.append("❌ buy_alert_enabled = NO (alertas BUY deshabilitadas)")
            
            # Verificar señal
            if not buy_signal:
                issues.append("❌ Señal BUY = NO (condiciones técnicas no cumplidas)")
                
                # Analizar condiciones específicas
                print("   📊 Análisis de condiciones técnicas:")
                
                # RSI check (depende del preset)
                rsi_threshold = 50  # Default, pero depende del preset
                if preset == "swing":
                    rsi_threshold = 40 if sl_tp_mode == "conservative" else 45
                elif preset == "intraday":
                    rsi_threshold = 45 if sl_tp_mode == "conservative" else 50
                elif preset == "scalp":
                    rsi_threshold = 50
                
                if rsi is not None:
                    if rsi >= rsi_threshold:
                        issues.append(f"   ⚠️  RSI={rsi:.2f} >= {rsi_threshold} (umbral requerido)")
                    else:
                        print(f"   ✅ RSI={rsi:.2f} < {rsi_threshold} (cumple)")
                
                # EMA10 check
                if ema10 and price:
                    if price <= ema10:
                        issues.append(f"   ⚠️  Precio ${price:.4f} <= EMA10 ${ema10:.4f}")
                    else:
                        print(f"   ✅ Precio ${price:.4f} > EMA10 ${ema10:.4f}")
                
                # Volume check
                if volume_ratio is not None:
                    if volume_ratio < 0.5:
                        issues.append(f"   ⚠️  Volume ratio {volume_ratio:.2f}x < 0.5x (mínimo requerido)")
                    else:
                        print(f"   ✅ Volume ratio {volume_ratio:.2f}x >= 0.5x")
            
            # Verificar throttle (si hay información disponible)
            print()
            print("5️⃣ VERIFICACIÓN DE THROTTLE/COOLDOWN")
            print("-" * 70)
            print("   ℹ️  Para verificar throttle, revisa los logs del backend")
            print("   ℹ️  O consulta el endpoint de monitoring si está disponible")
            print()
            
            # Resumen final
            print("6️⃣ RESUMEN Y RECOMENDACIONES")
            print("-" * 70)
            
            if alert_enabled and buy_alert_enabled and buy_signal:
                print("   ✅ TODO CORRECTO:")
                print("      • Flags habilitados")
                print("      • Señal BUY presente")
                print("      → La alerta DEBERÍA saltar")
                print("      → Si no salta, verificar logs del backend para throttle/cooldown")
            else:
                print("   🚫 PROBLEMAS ENCONTRADOS:")
                for issue in issues:
                    print(f"      {issue}")
                
                print()
                print("   💡 SOLUCIONES:")
                if not alert_enabled:
                    print("      → Habilitar alert_enabled en el Dashboard")
                if not buy_alert_enabled:
                    print("      → Habilitar buy_alert_enabled en el Dashboard")
                if not buy_signal:
                    print("      → Esperar a que se cumplan las condiciones técnicas")
                    print("      → O ajustar la estrategia/preset si es necesario")
        
        else:
            print(f"   ⚠️  Error al consultar señales: {response.status_code}")
            print(f"   → Respuesta: {response.text[:200]}")
        
        print()
        print("=" * 70)
        print("✅ DIAGNÓSTICO COMPLETADO")
        print("=" * 70)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    diagnose()











