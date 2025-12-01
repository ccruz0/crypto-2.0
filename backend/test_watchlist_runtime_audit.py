#!/usr/bin/env python3
"""
Runtime Audit Script for Watchlist
Tests backend API responses and validates against Business Rules
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketData, MarketPrice
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import resolve_strategy_profile
from app.api.routes_market import get_top_coins_with_prices
from fastapi.testclient import TestClient
from app.main import app
import json
from typing import Dict, List, Any

def test_strategy_state_for_symbol(symbol: str, db) -> Dict[str, Any]:
    """Test strategy_state calculation for a specific symbol"""
    print(f"\n{'='*60}")
    print(f"Testing: {symbol}")
    print(f"{'='*60}")
    
    # Get watchlist item
    try:
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        )
        # Try to filter by is_deleted if column exists
        if hasattr(WatchlistItem, 'is_deleted'):
            watchlist_item = watchlist_item.filter(WatchlistItem.is_deleted == False)
        watchlist_item = watchlist_item.first()
    except Exception as e:
        # Fallback: query without is_deleted
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
    
    if not watchlist_item:
        return {"error": f"No watchlist item found for {symbol}"}
    
    # Get market data
    md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
    mp = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
    
    current_price = mp.price if mp and mp.price else (watchlist_item.price if watchlist_item.price else None)
    rsi = md.rsi if md and md.rsi else (watchlist_item.rsi if watchlist_item.rsi else None)
    ma50 = md.ma50 if md and md.ma50 else None
    ma200 = md.ma200 if md and md.ma200 else None
    ema10 = md.ema10 if md and md.ema10 else None
    volume = md.current_volume if md and md.current_volume else None
    avg_volume = md.avg_volume if md and md.avg_volume else None
    
    if not current_price:
        return {"error": f"No price data for {symbol}"}
    
    # Resolve strategy profile
    strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
    
    # Calculate signals
    signals = calculate_trading_signals(
        symbol=symbol,
        price=current_price,
        rsi=rsi,
        ma50=ma50,
        ma200=ma200,
        ema10=ema10,
        volume=volume,
        avg_volume=avg_volume,
        buy_target=watchlist_item.buy_target,
        strategy_type=strategy_type,
        risk_approach=risk_approach,
    )
    
    strategy_state = signals.get("strategy", {})
    buy_signal = signals.get("buy_signal", False)
    decision = strategy_state.get("decision", "WAIT")
    index = strategy_state.get("index")
    reasons = strategy_state.get("reasons", {})
    
    # Validate canonical BUY rule
    buy_flags = {
        "buy_rsi_ok": reasons.get("buy_rsi_ok"),
        "buy_ma_ok": reasons.get("buy_ma_ok"),
        "buy_volume_ok": reasons.get("buy_volume_ok"),
        "buy_target_ok": reasons.get("buy_target_ok"),
        "buy_price_ok": reasons.get("buy_price_ok"),
    }
    
    buy_flags_boolean = {k: v for k, v in buy_flags.items() if isinstance(v, bool)}
    all_buy_flags_true = bool(buy_flags_boolean) and all(b is True for b in buy_flags_boolean.values())
    
    # Check canonical rule compliance
    canonical_rule_ok = True
    issues = []
    
    if all_buy_flags_true:
        if decision != "BUY":
            canonical_rule_ok = False
            issues.append(f"❌ VIOLATION: All buy_* flags True but decision={decision} (should be BUY)")
        if not buy_signal:
            canonical_rule_ok = False
            issues.append(f"❌ VIOLATION: All buy_* flags True but buy_signal={buy_signal} (should be True)")
        if index != 100:
            canonical_rule_ok = False
            issues.append(f"❌ VIOLATION: All buy_* flags True but index={index} (should be 100)")
    else:
        if decision == "BUY":
            canonical_rule_ok = False
            issues.append(f"❌ VIOLATION: decision=BUY but not all buy_* flags are True")
    
    result = {
        "symbol": symbol,
        "price": current_price,
        "rsi": rsi,
        "ma50": ma50,
        "ema200": ma200,
        "ema10": ema10,
        "volume_ratio": signals.get("volume_ratio"),
        "strategy_type": strategy_type.value,
        "risk_approach": risk_approach.value,
        "decision": decision,
        "buy_signal": buy_signal,
        "index": index,
        "buy_flags": buy_flags,
        "all_buy_flags_true": all_buy_flags_true,
        "canonical_rule_ok": canonical_rule_ok,
        "issues": issues,
        "alert_enabled": watchlist_item.alert_enabled,
        "buy_alert_enabled": getattr(watchlist_item, "buy_alert_enabled", False),
        "trade_enabled": watchlist_item.trade_enabled,
    }
    
    print(f"Decision: {decision}")
    print(f"Buy Signal: {buy_signal}")
    print(f"Index: {index}%")
    print(f"All Buy Flags True: {all_buy_flags_true}")
    print(f"Canonical Rule OK: {canonical_rule_ok}")
    print(f"Buy Flags: {buy_flags}")
    if issues:
        print(f"Issues: {issues}")
    
    return result

def test_api_response(symbol: str) -> Dict[str, Any]:
    """Test API response for a symbol"""
    client = TestClient(app)
    
    # Test /api/market/top-coins-data endpoint
    response = client.get("/api/market/top-coins-data")
    if response.status_code != 200:
        return {"error": f"API returned {response.status_code}"}
    
    data = response.json()
    coins = data.get("coins", [])
    
    coin = next((c for c in coins if c.get("instrument_name") == symbol), None)
    if not coin:
        return {"error": f"Symbol {symbol} not found in API response"}
    
    strategy_state = coin.get("strategy_state")
    signal = coin.get("signal")
    strategy = coin.get("strategy")
    
    return {
        "symbol": symbol,
        "signal": signal,
        "strategy_state": strategy_state,
        "strategy": strategy,
        "rsi": coin.get("rsi"),
        "ma50": coin.get("ma50"),
        "ema10": coin.get("ema10"),
        "volume_ratio": coin.get("volume_ratio"),
    }

def main():
    """Run runtime audit"""
    print("="*60)
    print("WATCHLIST RUNTIME AUDIT")
    print("="*60)
    
    db = SessionLocal()
    
    try:
        # Test special symbols
        test_symbols = ["ALGO_USDT", "LDO_USDT", "TON_USDT"]
        
        results = []
        for symbol in test_symbols:
            result = test_strategy_state_for_symbol(symbol, db)
            results.append(result)
            
            # Also test API response
            api_result = test_api_response(symbol)
            print(f"\nAPI Response for {symbol}:")
            print(f"  Signal: {api_result.get('signal')}")
            print(f"  Strategy State Decision: {api_result.get('strategy_state', {}).get('decision')}")
            print(f"  Strategy State Index: {api_result.get('strategy_state', {}).get('index')}")
            
            # Compare backend calculation vs API response
            if result.get("decision") and api_result.get("strategy_state", {}).get("decision"):
                if result["decision"] != api_result["strategy_state"]["decision"]:
                    print(f"  ❌ MISMATCH: Backend decision={result['decision']} but API decision={api_result['strategy_state']['decision']}")
                else:
                    print(f"  ✅ Match: Both show decision={result['decision']}")
        
        # Summary
        print("\n" + "="*60)
        print("AUDIT SUMMARY")
        print("="*60)
        
        all_ok = True
        for result in results:
            if not result.get("canonical_rule_ok", True):
                all_ok = False
            if result.get("issues"):
                all_ok = False
        
        if all_ok:
            print("✅ All tests passed - Canonical BUY rule is correctly implemented")
        else:
            print("❌ Issues found - See details above")
        
        return results
        
    finally:
        db.close()

if __name__ == "__main__":
    main()

