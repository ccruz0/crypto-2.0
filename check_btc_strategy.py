#!/usr/bin/env python3
"""Script para consultar la estrategia actual de BTC_USDT"""
import sys
import os
import json

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

def get_btc_strategy():
    """Obtiene la estrategia completa de BTC_USDT"""
    print("="*80)
    print("📊 ESTRATEGIA ACTUAL PARA BTC_USDT")
    print("="*80)
    print()
    
    # 1. Trading Config (preset)
    print("1️⃣ CONFIGURACIÓN DE TRADING (trading_config.json)")
    print("-"*80)
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'backend', 'trading_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        btc_config = config.get('coins', {}).get('BTC_USDT', {})
        preset_name = btc_config.get('preset', 'swing')
        preset_config = config.get('presets', {}).get(preset_name, {})
        
        print(f"   📋 Preset: {preset_name}")
        print(f"   📊 Parámetros del preset:")
        for key, value in preset_config.items():
            print(f"      • {key}: {value}")
        
        overrides = btc_config.get('overrides', {})
        if overrides:
            print(f"   🔧 Overrides personalizados:")
            for key, value in overrides.items():
                print(f"      • {key}: {value}")
        else:
            print(f"   ℹ️  Sin overrides personalizados")
        
    except Exception as e:
        print(f"   ❌ Error leyendo trading_config.json: {e}")
    
    print()
    
    # 2. SL/TP Strategy
    print("2️⃣ ESTRATEGIA SL/TP")
    print("-"*80)
    print("   📉 Stop Loss:")
    print("      • Conservative: 2x ATR (más amplio, menos probable que se active)")
    print("      • Aggressive: 1x ATR (más ajustado, más probable que se active)")
    print()
    print("   📈 Take Profit:")
    print("      • Conservative: 3x ATR (objetivo más alto, menos probable)")
    print("      • Aggressive: 2x ATR (objetivo más bajo, más probable)")
    print()
    print("   ℹ️  Los porcentajes se calculan dinámicamente basados en ATR")
    print("   ℹ️  El modo por defecto es 'conservative'")
    print()
    
    # 3. Signal Criteria
    print("3️⃣ CRITERIOS DE SEÑALES (basado en preset 'swing')")
    print("-"*80)
    print("   🟢 CRITERIOS BUY (todos deben cumplirse):")
    print("      • RSI < 40 (actual: se compara con precio actual)")
    print("      • MA50 > EMA10 (verificación de tendencia alcista)")
    print("      • Precio ≤ buy_target (si está configurado)")
    print("      • Volume ≥ 2x promedio (último período vs promedio 10 períodos)")
    print()
    print("   ℹ️  NOTA: Si los MAs no están disponibles, la verificación de MA no bloquea la señal")
    print("   ℹ️  NOTA: El backend verifica MA50 > EMA10 en trading_signals.py (líneas 105-114)")
    print()
    print("   🔴 CRITERIOS SELL (todos deben cumplirse):")
    print("      • RSI > 70 (actual: se compara con precio actual)")
    print("      • MA50 < EMA10 (diferencia ≥0.5%) - reversión de tendencia")
    print("      • Volume ≥ 2x promedio")
    print()
    
    # 4. Alert Status
    print("4️⃣ ESTADO DE ALERTAS")
    print("-"*80)
    print("   ✅ alert_enabled: True (BTC_USDT es la única moneda con alertas activas)")
    print("   ℹ️  Esto significa que BTC_USDT recibirá:")
    print("      • Alertas automáticas cuando se detecten señales BUY/SELL")
    print("      • Creación automática de órdenes cuando se cumplan los criterios")
    print()
    
    # 5. Summary
    print("="*80)
    print("📋 RESUMEN DE ESTRATEGIA BTC_USDT")
    print("="*80)
    print(f"   • Preset: {preset_name}")
    print(f"   • RSI Buy Threshold: {preset_config.get('RSI_BUY', 'N/A')}")
    print(f"   • RSI Sell Threshold: {preset_config.get('RSI_SELL', 'N/A')}")
    print(f"   • SL/TP Mode: conservative (por defecto)")
    print(f"   • SL: 2x ATR (conservative) o 1x ATR (aggressive)")
    print(f"   • TP: 3x ATR (conservative) o 2x ATR (aggressive)")
    print(f"   • Alertas: ACTIVAS (alert_enabled=True)")
    print("="*80)

if __name__ == "__main__":
    get_btc_strategy()

