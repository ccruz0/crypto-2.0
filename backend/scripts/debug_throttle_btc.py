#!/usr/bin/env python3
"""Debug script to simulate BTC throttle decisions.

This script loads config for BTC and runs several hypothetical price updates
at different times, printing whether each would be allowed or blocked and why.
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.signal_throttle import (
    should_emit_signal,
    SignalThrottleConfig,
    LastSignalSnapshot,
)
from app.services.config_loader import get_alert_thresholds


def simulate_btc_throttle():
    """Simulate BTC throttle decisions with various scenarios."""
    symbol = "BTC_USDT"
    strategy_key = "swing:conservative"
    
    # Get config from system
    try:
        min_price_change_pct, cooldown_minutes = get_alert_thresholds(symbol, strategy_key)
        if min_price_change_pct is None:
            min_price_change_pct = 1.0
        if cooldown_minutes is None:
            cooldown_minutes = 5.0
    except Exception as e:
        print(f"⚠️  Could not load config: {e}, using defaults")
        min_price_change_pct = 1.0
        cooldown_minutes = 5.0
    
    config = SignalThrottleConfig(
        min_price_change_pct=min_price_change_pct,
        min_interval_minutes=cooldown_minutes,
    )
    
    print(f"\n{'='*80}")
    print(f"BTC Throttle Debug Simulation")
    print(f"{'='*80}")
    print(f"Symbol: {symbol}")
    print(f"Strategy: {strategy_key}")
    print(f"Config: min_price_change_pct={min_price_change_pct}%, min_interval_minutes={cooldown_minutes}m")
    print(f"{'='*80}\n")
    
    base_time = datetime.now(timezone.utc)
    base_price = 50000.0
    
    scenarios = [
        {
            "name": "First alert (no previous signal)",
            "time_offset": timedelta(minutes=0),
            "price": base_price,
            "last_same_side": None,
            "last_opposite_side": None,
        },
        {
            "name": "Second alert: 2 min later, 0.3% change (BLOCKED - time AND price fail)",
            "time_offset": timedelta(minutes=2),
            "price": base_price * 1.003,  # 0.3% change
            "last_same_side": LastSignalSnapshot(
                side="BUY",
                price=base_price,
                timestamp=base_time,
            ),
            "last_opposite_side": None,
        },
        {
            "name": "Third alert: 10 min later, 0.3% change (BLOCKED - price fails)",
            "time_offset": timedelta(minutes=10),
            "price": base_price * 1.003,  # Still only 0.3% change
            "last_same_side": LastSignalSnapshot(
                side="BUY",
                price=base_price,
                timestamp=base_time,
            ),
            "last_opposite_side": None,
        },
        {
            "name": "Fourth alert: 2 min later, 2% change (BLOCKED - time fails)",
            "time_offset": timedelta(minutes=12),
            "price": base_price * 1.02,  # 2% change
            "last_same_side": LastSignalSnapshot(
                side="BUY",
                price=base_price,
                timestamp=base_time + timedelta(minutes=10),
            ),
            "last_opposite_side": None,
        },
        {
            "name": "Fifth alert: 10 min later, 2% change (ALLOWED - both conditions met)",
            "time_offset": timedelta(minutes=20),
            "price": base_price * 1.02,  # 2% change
            "last_same_side": LastSignalSnapshot(
                side="BUY",
                price=base_price,
                timestamp=base_time + timedelta(minutes=10),
            ),
            "last_opposite_side": None,
        },
        {
            "name": "Direction change: SELL then BUY (ALLOWED - direction change resets)",
            "time_offset": timedelta(minutes=22),
            "price": base_price * 1.01,  # 1% change
            "last_same_side": LastSignalSnapshot(
                side="BUY",
                price=base_price,
                timestamp=base_time + timedelta(minutes=10),
            ),
            "last_opposite_side": LastSignalSnapshot(
                side="SELL",
                price=base_price * 1.015,
                timestamp=base_time + timedelta(minutes=21),  # More recent than BUY
            ),
        },
    ]
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"\nScenario {i}: {scenario['name']}")
        print("-" * 80)
        
        current_time = base_time + scenario["time_offset"]
        current_price = scenario["price"]
        
        allowed, metadata = should_emit_signal(
            symbol=symbol,
            side="BUY",
            current_price=current_price,
            current_time=current_time,
            config=config,
            last_same_side=scenario["last_same_side"],
            last_opposite_side=scenario["last_opposite_side"],
        )
        
        status = "✅ ALLOWED" if allowed else "❌ BLOCKED"
        print(f"Status: {status}")
        print(f"Reason: {metadata['reason']}")
        
        if scenario["last_same_side"]:
            time_since = metadata.get("time_since_last")
            price_change = metadata.get("price_change_pct")
            if time_since is not None:
                print(f"Time since last: {time_since:.2f} minutes")
            if price_change is not None:
                print(f"Price change: {price_change:.2f}%")
            print(f"Blocked by time: {metadata.get('blocked_by_time', False)}")
            print(f"Blocked by price: {metadata.get('blocked_by_price', False)}")
        
        print(f"Current price: ${current_price:,.2f}")
        print(f"Current time: {current_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    print(f"\n{'='*80}")
    print("Summary:")
    print("  - First alert: Always allowed")
    print("  - Subsequent alerts: Require BOTH time cooldown AND price change")
    print("  - Direction changes: Reset throttle (always allowed)")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    simulate_btc_throttle()






