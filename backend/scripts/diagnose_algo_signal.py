#!/usr/bin/env python3
"""
Quick diagnostic script to check why ALGO_USDT is not sending signals.
Run from backend directory: python3 scripts/diagnose_algo_signal.py
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.strategy_profiles import resolve_strategy_profile, StrategyType, RiskApproach
from app.services.config_loader import get_strategy_rules
from app.services.trading_signals import calculate_trading_signals
from app.models.market_price import MarketData

def main():
    symbol = "ALGO_USDT"
    db = SessionLocal()
    
    try:
        print(f"\n{'='*60}")
        print(f"DIAGNÓSTICO: {symbol}")
        print(f"{'='*60}\n")
        
        # 1. Check watchlist
        print("1. WATCHLIST STATUS:")
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not watchlist_item:
            print(f"   ❌ {symbol} NO está en el watchlist")
            return
        else:
            print(f"   ✅ {symbol} está en el watchlist")
            print(f"      - alert_enabled: {watchlist_item.alert_enabled}")
            print(f"      - buy_alert_enabled: {watchlist_item.buy_alert_enabled}")
            print(f"      - trade_enabled: {watchlist_item.trade_enabled}")
            print(f"      - amount_usd: {watchlist_item.trade_amount_usd}")
        
        if not watchlist_item.alert_enabled:
            print(f"\n   ⚠️  PROBLEMA: alert_enabled=False - las alertas están desactivadas")
            return
        
        # 2. Check strategy profile
        print(f"\n2. STRATEGY PROFILE:")
        strategy_type, risk_approach = resolve_strategy_profile(
            symbol=symbol,
            db=db,
            watchlist_item=watchlist_item
        )
        print(f"   - Strategy Type: {strategy_type.value if strategy_type else 'None'}")
        print(f"   - Risk Approach: {risk_approach.value if risk_approach else 'None'}")
        
        if not strategy_type or not risk_approach:
            print(f"   ❌ No se pudo resolver el perfil de estrategia")
            return
        
        # 3. Load strategy rules
        print(f"\n3. STRATEGY RULES:")
        rules = get_strategy_rules(strategy_type.value, risk_approach.value.capitalize())
        print(f"   - RSI buyBelow: {rules.get('rsi', {}).get('buyBelow')}")
        print(f"   - MA checks: {rules.get('maChecks', {})}")
        print(f"   - Volume min ratio: {rules.get('volumeMinRatio')}")
        
        # 4. Check market data
        print(f"\n4. MARKET DATA:")
        market_data = db.query(MarketData).filter(
            MarketData.symbol == symbol
        ).first()
        
        if not market_data:
            print(f"   ❌ No hay market data para {symbol}")
            return
        
        print(f"   - Price: ${market_data.price:.6f}")
        print(f"   - RSI: {market_data.rsi:.2f}" if market_data.rsi else "   - RSI: None")
        print(f"   - MA50: {market_data.ma50:.6f}" if market_data.ma50 else "   - MA50: None")
        print(f"   - EMA10: {market_data.ema10:.6f}" if market_data.ema10 else "   - EMA10: None")
        print(f"   - Volume: {market_data.volume:.2f}" if market_data.volume else "   - Volume: None")
        print(f"   - Avg Volume: {market_data.avg_volume:.2f}" if market_data.avg_volume else "   - Avg Volume: None")
        
        # 5. Calculate signals
        print(f"\n5. SIGNAL CALCULATION:")
        result = calculate_trading_signals(
            symbol=symbol,
            price=market_data.price,
            rsi=market_data.rsi,
            ma50=market_data.ma50,
            ma200=market_data.ma200,
            ema10=market_data.ema10,
            volume=market_data.volume,
            avg_volume=market_data.avg_volume,
            buy_target=watchlist_item.buy_target,
            last_buy_price=watchlist_item.purchase_price,
            strategy_type=strategy_type,
            risk_approach=risk_approach,
        )
        
        strategy = result.get("strategy", {})
        decision = strategy.get("decision")
        buy_signal = result.get("buy_signal")
        reasons = strategy.get("reasons", {})
        
        print(f"   - Decision: {decision}")
        print(f"   - Buy Signal: {buy_signal}")
        print(f"   - Index: {strategy.get('index')}%")
        print(f"\n   BUY FLAGS:")
        for key, value in reasons.items():
            if key.startswith("buy_"):
                status = "✅" if value is True else ("❌" if value is False else "⚪")
                print(f"      {status} {key}: {value}")
        
        # 6. Check conditions
        print(f"\n6. CONDITION CHECK:")
        rsi_buy_below = rules.get('rsi', {}).get('buyBelow')
        if market_data.rsi is not None and rsi_buy_below is not None:
            rsi_ok = market_data.rsi < rsi_buy_below
            print(f"   - RSI {market_data.rsi:.2f} < {rsi_buy_below}: {'✅' if rsi_ok else '❌'}")
        else:
            print(f"   - RSI check: {'✅ (no threshold)' if rsi_buy_below is None else '❌ (no RSI data)'}")
        
        volume_ratio = None
        if market_data.volume and market_data.avg_volume and market_data.avg_volume > 0:
            volume_ratio = market_data.volume / market_data.avg_volume
            min_volume_ratio = rules.get('volumeMinRatio', 0.5)
            vol_ok = volume_ratio >= min_volume_ratio
            print(f"   - Volume ratio {volume_ratio:.2f}x >= {min_volume_ratio}x: {'✅' if vol_ok else '❌'}")
        else:
            print(f"   - Volume check: ⚪ (no volume data)")
        
        ma_checks = rules.get('maChecks', {})
        if ma_checks.get('ema10') and market_data.ema10:
            ema_ok = market_data.price > market_data.ema10
            print(f"   - Price {market_data.price:.6f} > EMA10 {market_data.ema10:.6f}: {'✅' if ema_ok else '❌'}")
        elif not ma_checks.get('ema10'):
            print(f"   - EMA10 check: ✅ (not required)")
        
        if watchlist_item.buy_target:
            target_ok = market_data.price <= watchlist_item.buy_target
            print(f"   - Price {market_data.price:.6f} <= Buy Target {watchlist_item.buy_target:.6f}: {'✅' if target_ok else '❌'}")
        else:
            print(f"   - Buy Target: ⚪ (not set)")
        
        # 7. Summary
        print(f"\n7. SUMMARY:")
        if decision == "BUY" and buy_signal:
            print(f"   ✅ {symbol} DEBERÍA enviar señal BUY")
            print(f"      - Decision: {decision}")
            print(f"      - Buy Signal: {buy_signal}")
            print(f"      - Index: {strategy.get('index')}%")
        else:
            print(f"   ❌ {symbol} NO está enviando señal BUY")
            print(f"      - Decision: {decision}")
            print(f"      - Buy Signal: {buy_signal}")
            print(f"      - Index: {strategy.get('index')}%")
            print(f"\n   Razones por las que NO es BUY:")
            for key, value in reasons.items():
                if key.startswith("buy_") and value is not True:
                    print(f"      - {key}: {value}")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()

