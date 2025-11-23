#!/usr/bin/env python3
"""Script to show coins with TRADE ALERT YES and their proximity ratio to BUY/SELL alerts
Uses API instead of direct database access
Ratio 0-100: 100 = BUY ALERT, 0 = SELL ALERT
"""

import sys
import os
import requests
from typing import Dict, Optional

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from types import SimpleNamespace

from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import resolve_strategy_profile
from price_fetcher import get_price_with_fallback

def calculate_alert_ratio(signals: dict, rsi: float = None, price: float = None, 
                          buy_target: float = None, ma50: float = None, ema10: float = None) -> float:
    """
    Calculate alert ratio 0-100 where:
    - 100 = BUY ALERT (buy_signal=True)
    - 0 = SELL ALERT (sell_signal=True)
    - 50 = WAIT/NEUTRAL (between signals)
    
    For WAIT state, calculate based on:
    - RSI position (lower RSI = closer to BUY, higher RSI = closer to SELL)
    - Price vs buy_target (if exists)
    - MA50 vs EMA10 trend
    """
    # If BUY signal is active, return 100
    if signals.get("buy_signal", False):
        return 100.0
    
    # If SELL signal is active, return 0
    if signals.get("sell_signal", False):
        return 0.0
    
    # Both signals are False - calculate proximity ratio
    # Start with neutral (50)
    ratio = 50.0
    
    # Factor 1: RSI position (40% weight)
    # RSI < 40 = oversold (closer to BUY), RSI > 70 = overbought (closer to SELL)
    if rsi is not None:
        if rsi < 40:
            # Oversold: closer to BUY (60-100 range)
            rsi_ratio = 60 + ((40 - rsi) / 40) * 40  # RSI 0 = 100, RSI 40 = 60
        elif rsi > 70:
            # Overbought: closer to SELL (0-40 range)
            rsi_ratio = 40 - ((rsi - 70) / 30) * 40  # RSI 70 = 40, RSI 100 = 0
        else:
            # Neutral RSI (40-70): stay around 50
            rsi_ratio = 50 - ((rsi - 55) / 15) * 10  # RSI 40 = 60, RSI 55 = 50, RSI 70 = 40
        
        ratio = ratio * 0.6 + rsi_ratio * 0.4
    
    # Factor 2: Price vs buy_target (30% weight)
    if buy_target is not None and price is not None and buy_target > 0:
        if price <= buy_target:
            # Price at or below target: closer to BUY
            target_ratio = 70 + min(30, (buy_target - price) / buy_target * 30)
        else:
            # Price above target: further from BUY
            price_diff_pct = ((price - buy_target) / buy_target) * 100
            if price_diff_pct > 10:
                target_ratio = 30  # More than 10% above target
            else:
                target_ratio = 70 - (price_diff_pct / 10) * 40  # Gradual decrease
        
        ratio = ratio * 0.7 + target_ratio * 0.3
    
    # Factor 3: MA50 vs EMA10 trend (30% weight)
    if ma50 is not None and ema10 is not None and ma50 > 0 and ema10 > 0:
        if ma50 > ema10:
            # Uptrend: closer to BUY
            trend_ratio = 60 + min(40, ((ma50 - ema10) / ema10) * 100)
        else:
            # Downtrend: closer to SELL
            trend_ratio = 40 - min(40, ((ema10 - ma50) / ma50) * 100)
        
        # Apply trend factor only if we don't have buy_target
        if buy_target is None:
            ratio = ratio * 0.7 + trend_ratio * 0.3
        else:
            # If we have buy_target, give less weight to trend
            ratio = ratio * 0.9 + trend_ratio * 0.1
    
    # Ensure ratio stays within 0-100 bounds
    return max(0.0, min(100.0, ratio))

def get_ratio_label(ratio: float) -> str:
    """Get a label for the ratio"""
    if ratio >= 80:
        return "🟢 MUY CERCA BUY"
    elif ratio >= 60:
        return "🟡 CERCA BUY"
    elif ratio >= 40:
        return "⚪ NEUTRAL"
    elif ratio >= 20:
        return "🟠 CERCA SELL"
    else:
        return "🔴 MUY CERCA SELL"

def get_watchlist_from_api(base_url: str = "http://localhost:8000") -> list:
    """Get watchlist items from API"""
    try:
        # Try local first
        response = requests.get(f"{base_url}/api/dashboard", timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    
    # Try AWS
    try:
        aws_url = "http://54.254.150.31:8000"
        response = requests.get(f"{aws_url}/api/dashboard", timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    
    return None

def main():
    print("=" * 100)
    print("📊 RATIO DE PROXIMIDAD A ALERTAS BUY/SELL")
    print("=" * 100)
    print("Ratio 0-100: 100 = BUY ALERT | 0 = SELL ALERT | 50 = WAIT/NEUTRAL")
    print("=" * 100)
    print()
    
    # Try to get watchlist from API
    print("🔍 Intentando conectar con el backend...")
    watchlist_data = get_watchlist_from_api()
    
    if watchlist_data is None:
        print("❌ No se pudo conectar al backend (ni local ni AWS)")
        print("\n💡 SOLUCIONES:")
        print("   1. Inicia el backend localmente:")
        print("      cd /Users/carloscruz/automated-trading-platform")
        print("      docker-compose up -d backend")
        print("\n   2. O verifica que el backend esté corriendo en:")
        print("      - Local: http://localhost:8000")
        print("      - AWS: http://54.254.150.31:8000")
        return
    
    # Filter items with alert_enabled=True
    alert_items = [item for item in watchlist_data if item.get("alert_enabled", False)]
    
    if not alert_items:
        print("❌ No se encontraron monedas con TRADE ALERT YES.")
        return
    
    print(f"✅ Encontradas {len(alert_items)} monedas con TRADE ALERT YES\n")
    print("-" * 100)
    
    results = []
    
    for item in alert_items:
        symbol = item.get("symbol")
        if not symbol:
            continue
        
        try:
            # Get price data with indicators
            result = get_price_with_fallback(symbol, "15m")
            current_price = result.get('price', 0)
            
            if not current_price or current_price <= 0:
                print(f"⚠️  {symbol:15s} | Sin datos de precio")
                continue
            
            rsi = result.get('rsi', 50)
            ma50 = result.get('ma50', current_price)
            ma200 = result.get('ma200', current_price)
            ema10 = result.get('ma10', current_price)
            atr = result.get('atr', current_price * 0.02)
            volume_24h = result.get('volume_24h', 0)
            avg_volume = result.get('avg_volume', volume_24h)
            
            # Calculate resistance levels
            price_precision = 2 if current_price >= 100 else 4
            res_up = round(current_price * 1.02, price_precision)
            res_down = round(current_price * 0.98, price_precision)
            
            # Get buy_target and purchase_price from item
            buy_target = item.get("buy_target")
            purchase_price = item.get("purchase_price")
            last_buy_price = purchase_price if purchase_price and purchase_price > 0 else None
            trade_amount_usd = item.get("trade_amount_usd") or 100.0
            
            proxy_item = SimpleNamespace(**item)
            strategy_type, risk_approach = resolve_strategy_profile(symbol, None, proxy_item)

            # Calculate trading signals
            signals = calculate_trading_signals(
                symbol=symbol,
                price=current_price,
                rsi=rsi,
                atr14=atr,
                ma50=ma50,
                ma200=ma200,
                ema10=ema10,
                ma10w=ma200,  # Use MA200 as MA10w approximation
                volume=volume_24h,
                avg_volume=avg_volume,
                resistance_up=res_up,
                buy_target=buy_target,
                last_buy_price=last_buy_price,
                position_size_usd=trade_amount_usd,
                rsi_buy_threshold=40,
                rsi_sell_threshold=70,
                strategy_type=strategy_type,
                risk_approach=risk_approach,
            )
            
            # Calculate alert ratio
            ratio = calculate_alert_ratio(
                signals=signals,
                rsi=rsi,
                price=current_price,
                buy_target=buy_target,
                ma50=ma50,
                ema10=ema10
            )
            
            # Determine current signal state
            if signals.get("buy_signal", False):
                signal_state = "🟢 BUY"
            elif signals.get("sell_signal", False):
                signal_state = "🔴 SELL"
            else:
                signal_state = "⚪ WAIT"
            
            ratio_label = get_ratio_label(ratio)
            
            results.append({
                'symbol': symbol,
                'ratio': ratio,
                'signal_state': signal_state,
                'ratio_label': ratio_label,
                'price': current_price,
                'rsi': rsi,
                'buy_target': buy_target,
                'trade_enabled': item.get("trade_enabled", False)
            })
            
        except Exception as e:
            print(f"❌ Error procesando {symbol}: {e}")
            continue
    
    if not results:
        print("❌ No se pudieron procesar monedas (sin datos de precio)")
        return
    
    # Sort by ratio (highest first - closest to BUY)
    results.sort(key=lambda x: x['ratio'], reverse=True)
    
    # Print results
    print(f"{'#':<4} {'Symbol':<15} {'Ratio':<8} {'Estado':<15} {'Label':<20} {'Precio':<12} {'RSI':<8} {'Buy Target':<12} {'Trade':<8}")
    print("-" * 100)
    
    for index, result in enumerate(results, start=1):
        buy_target_str = f"${result['buy_target']:.4f}" if result['buy_target'] else "N/A"
        trade_str = "✅ YES" if result['trade_enabled'] else "❌ NO"
        
        print(f"{index:<4} {result['symbol']:<15} {result['ratio']:>6.1f}   {result['signal_state']:<15} {result['ratio_label']:<20} "
              f"${result['price']:>10.4f} {result['rsi']:>6.1f} {buy_target_str:>12} {trade_str:<8}")
    
    print("-" * 100)
    print(f"\n📊 Resumen:")
    print(f"   - Total monedas: {len(results)}")
    print(f"   - Con señal BUY activa: {sum(1 for r in results if 'BUY' in r['signal_state'])}")
    print(f"   - Con señal SELL activa: {sum(1 for r in results if 'SELL' in r['signal_state'])}")
    print(f"   - En estado WAIT: {sum(1 for r in results if 'WAIT' in r['signal_state'])}")
    print(f"   - Ratio promedio: {sum(r['ratio'] for r in results) / len(results):.1f}")
    if results:
        print(f"   - Más cerca de BUY: {results[0]['symbol']} (ratio: {results[0]['ratio']:.1f})")
        print(f"   - Más cerca de SELL: {results[-1]['symbol']} (ratio: {results[-1]['ratio']:.1f})")

if __name__ == "__main__":
    main()

