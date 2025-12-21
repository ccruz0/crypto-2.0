#!/usr/bin/env python3
"""
Diagnostic script to investigate why sell alerts are not being generated.

This script checks:
1. sell_alert_enabled flags in database
2. Current RSI values vs sell thresholds
3. MA reversal conditions (MA50 < EMA10)
4. Volume confirmation
5. Throttle status
6. Signal monitor service status
"""

import sys
import os
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice, MarketData
from app.services.signal_evaluator import evaluate_signal_for_symbol
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import resolve_strategy_profile
from datetime import datetime, timezone
import json

def check_sell_alert_configuration():
    """Check sell_alert_enabled flags for all watchlist items"""
    db: Session = SessionLocal()
    try:
        print("=" * 80)
        print("SELL ALERT CONFIGURATION CHECK")
        print("=" * 80)
        
        items = db.query(WatchlistItem).filter(
            WatchlistItem.alert_enabled == True,
            WatchlistItem.deleted == False
        ).all()
        
        print(f"\nFound {len(items)} items with alert_enabled=True")
        print("\nSymbol | alert_enabled | buy_alert_enabled | sell_alert_enabled | Trade")
        print("-" * 80)
        
        sell_enabled_count = 0
        for item in items:
            sell_enabled = getattr(item, 'sell_alert_enabled', False)
            buy_enabled = getattr(item, 'buy_alert_enabled', False)
            if sell_enabled:
                sell_enabled_count += 1
            
            status = "✅" if sell_enabled else "❌"
            print(f"{item.symbol:15} | {item.alert_enabled!s:13} | {buy_enabled!s:17} | {sell_enabled!s:18} | {item.trade_enabled!s:5} {status}")
        
        print(f"\nSummary: {sell_enabled_count}/{len(items)} symbols have sell_alert_enabled=True")
        return items
    finally:
        db.close()

def check_current_signals(symbols: list = None):
    """Check current sell signals for symbols"""
    db: Session = SessionLocal()
    try:
        print("\n" + "=" * 80)
        print("CURRENT SELL SIGNAL ANALYSIS")
        print("=" * 80)
        
        if symbols is None:
            items = db.query(WatchlistItem).filter(
                WatchlistItem.alert_enabled == True,
                WatchlistItem.deleted == False
            ).all()
            symbols = [item.symbol for item in items]
        
        print(f"\nAnalyzing {len(symbols)} symbols...\n")
        
        results = []
        for symbol in symbols[:10]:  # Limit to first 10 for readability
            try:
                item = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol == symbol,
                    WatchlistItem.alert_enabled == True,
                    WatchlistItem.deleted == False
                ).first()
                
                if not item:
                    continue
                
                # Evaluate signal
                eval_result = evaluate_signal_for_symbol(db, item, symbol)
                
                # Get market data
                mp = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
                md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
                
                current_price = mp.price if mp and mp.price else 0
                rsi = md.rsi if md and md.rsi is not None else None
                ma50 = md.ma50 if md and md.ma50 is not None else None
                ema10 = md.ema10 if md and md.ema10 is not None else None
                
                sell_alert_enabled = getattr(item, 'sell_alert_enabled', False)
                
                # Determine why sell alert is/isn't being sent
                reasons = []
                if not eval_result["sell_signal"]:
                    reasons.append("No sell_signal detected")
                    if rsi is None:
                        reasons.append("RSI missing")
                    elif rsi <= 70:
                        reasons.append(f"RSI {rsi:.1f} <= 70 (threshold)")
                    if ma50 is not None and ema10 is not None:
                        if ma50 >= ema10:
                            reasons.append(f"MA reversal not met (MA50 {ma50:.2f} >= EMA10 {ema10:.2f})")
                    if not eval_result["debug_flags"].get("sell_volume_ok", False):
                        reasons.append("Volume confirmation failed")
                else:
                    if not sell_alert_enabled:
                        reasons.append("sell_alert_enabled=False")
                    if not eval_result["sell_flag_allowed"]:
                        reasons.append("sell_flag_allowed=False")
                    if not eval_result["can_emit_sell_alert"]:
                        reasons.append("Throttle blocked")
                        reasons.append(f"Throttle reason: {eval_result['throttle_reason_sell']}")
                
                results.append({
                    "symbol": symbol,
                    "rsi": rsi,
                    "price": current_price,
                    "ma50": ma50,
                    "ema10": ema10,
                    "sell_signal": eval_result["sell_signal"],
                    "sell_alert_enabled": sell_alert_enabled,
                    "can_emit": eval_result["can_emit_sell_alert"],
                    "reasons": reasons,
                    "debug_flags": eval_result["debug_flags"]
                })
                
                # Print summary
                status = "🔴 SELL" if eval_result["sell_signal"] else "⏸️  WAIT"
                alert_status = "✅ ENABLED" if sell_alert_enabled else "❌ DISABLED"
                can_emit_status = "✅ CAN EMIT" if eval_result["can_emit_sell_alert"] else "❌ BLOCKED"
                
                print(f"{symbol:15} | {status:10} | Alert: {alert_status:12} | Emit: {can_emit_status}")
                if reasons:
                    print(f"  └─ Reasons: {', '.join(reasons)}")
                if rsi:
                    print(f"  └─ RSI: {rsi:.2f}, MA50: {ma50:.2f if ma50 else 'N/A'}, EMA10: {ema10:.2f if ema10 else 'N/A'}")
                print()
                
            except Exception as e:
                print(f"❌ Error analyzing {symbol}: {e}")
                import traceback
                traceback.print_exc()
        
        return results
    finally:
        db.close()

def check_monitoring_endpoint():
    """Check if monitoring endpoint is accessible"""
    print("\n" + "=" * 80)
    print("MONITORING ENDPOINT CHECK")
    print("=" * 80)
    
    try:
        import requests
        # Try to access monitoring endpoint
        # Note: This assumes the backend is running locally or we have the URL
        # For AWS, we'd need the actual URL
        print("\n⚠️  Monitoring endpoint check requires backend URL")
        print("   Check dashboard.hilovivo.com/api/monitoring/summary manually")
    except Exception as e:
        print(f"❌ Error checking monitoring endpoint: {e}")

def main():
    print("\n" + "🔍" * 40)
    print("SELL ALERT DIAGNOSTIC TOOL")
    print("🔍" * 40 + "\n")
    
    # Check configuration
    items = check_sell_alert_configuration()
    
    # Check current signals
    check_current_signals()
    
    # Check monitoring
    check_monitoring_endpoint()
    
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    print("""
1. Verify sell_alert_enabled=True for symbols you want sell alerts
2. Check RSI values - should be > 70 for sell signals
3. Verify MA reversal condition (MA50 < EMA10)
4. Check volume confirmation (sell_volume_ok)
5. Review throttle status - alerts may be throttled
6. Check backend logs for signal_monitor service errors
7. Verify monitoring endpoint is accessible (currently showing 500)
    """)

if __name__ == "__main__":
    main()




