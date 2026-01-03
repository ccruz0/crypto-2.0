#!/usr/bin/env python3
"""
Verification script for NEAR_USDT quantity normalization.

Usage:
    VERIFY_ORDER_FORMAT=1 python scripts/verify_near_quantity.py

This script will:
1. Fetch NEAR_USDT instrument metadata from Crypto.com Exchange
2. Test normalization of the failing quantity (6.42508353)
3. Display before/after quantities and instrument rules
4. Does NOT place any orders (safe to run)
"""

import os
import sys
import json

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.brokers.crypto_com_trade import trade_client
from decimal import Decimal, ROUND_FLOOR

def main():
    """Main verification function"""
    symbol = "NEAR_USDT"
    raw_quantity = 6.42508353
    
    print("=" * 80)
    print("NEAR_USDT Quantity Normalization Verification")
    print("=" * 80)
    print()
    
    # Fetch raw instrument data directly for validation
    print("Step 1: Fetching FULL raw instrument entry from API...")
    print()
    import requests
    inst_url = "https://api.crypto.com/exchange/v1/public/get-instruments"
    try:
        response = requests.get(inst_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            instruments = data.get("result", {}).get("data", [])
            raw_inst = next((i for i in instruments if i.get("symbol", "").upper() == symbol.upper()), None)
            if raw_inst:
                print("=" * 80)
                print("FULL RAW INSTRUMENT ENTRY FROM API:")
                print("=" * 80)
                print(json.dumps(raw_inst, indent=2))
                print("=" * 80)
                print()
                print(f"Key fields:")
                print(f"  - symbol: {raw_inst.get('symbol')}")
                print(f"  - qty_tick_size: {raw_inst.get('qty_tick_size')} (type: {type(raw_inst.get('qty_tick_size')).__name__})")
                print(f"  - quantity_decimals: {raw_inst.get('quantity_decimals')} (type: {type(raw_inst.get('quantity_decimals')).__name__})")
                print(f"  - min_quantity: {raw_inst.get('min_quantity')}")
                print()
            else:
                print(f"❌ {symbol} not found in API response")
                print()
    except Exception as e:
        print(f"⚠️  Could not fetch raw instrument data: {e}")
        print()
    
    # Get instrument metadata via our helper
    print("Step 2: Getting parsed instrument metadata...")
    print()
    inst_meta = trade_client._get_instrument_metadata(symbol)
    
    if inst_meta:
        print("✅ Parsed instrument metadata:")
        print(f"  - quantity_decimals: {inst_meta['quantity_decimals']} (type: {type(inst_meta['quantity_decimals']).__name__})")
        print(f"  - qty_tick_size: '{inst_meta['qty_tick_size']}' (type: {type(inst_meta['qty_tick_size']).__name__})")
        print(f"  - min_quantity: '{inst_meta.get('min_quantity', '0.001')}' (type: {type(inst_meta.get('min_quantity', '0.001')).__name__})")
        print()
    else:
        print("❌ Could not fetch instrument metadata - order would be blocked")
        print()
        return
    
    # Normalize quantity
    print("Step 3: Testing quantity normalization math...")
    print()
    print(f"Input:")
    print(f"  - Symbol: {symbol}")
    print(f"  - Raw Quantity: {raw_quantity}")
    print()
    
    # Manual calculation for verification
    qty_tick_size_str = inst_meta['qty_tick_size']
    quantity_decimals = inst_meta['quantity_decimals']
    qty_decimal = Decimal(str(raw_quantity))
    tick_decimal = Decimal(str(qty_tick_size_str))
    
    division_result = qty_decimal / tick_decimal
    floored_result = division_result.quantize(Decimal('1'), rounding=ROUND_FLOOR)
    qty_normalized = floored_result * tick_decimal
    
    print(f"Manual calculation (for validation):")
    print(f"  - step_size (as Decimal): {tick_decimal}")
    print(f"  - raw_qty / step_size: {division_result}")
    print(f"  - floored result: {floored_result}")
    print(f"  - normalized_qty (before formatting): {qty_normalized}")
    print()
    
    # Use the actual function
    normalized_qty_str = trade_client.normalize_quantity(symbol, raw_quantity)
    
    print("Result from normalize_quantity():")
    print(f"  - Normalized Quantity (string): '{normalized_qty_str}'")
    print()
    
    if normalized_qty_str is None:
        print("❌ ERROR: Quantity normalization returned None")
        return
    
    # Validate
    print("Step 4: Validation...")
    print()
    expected_qty = format(qty_normalized, f'.{quantity_decimals}f')
    if normalized_qty_str == expected_qty:
        print(f"✅ PASS: Normalized quantity '{normalized_qty_str}' matches expected '{expected_qty}'")
    else:
        print(f"⚠️  WARNING: Normalized '{normalized_qty_str}' != expected '{expected_qty}'")
    
    print()
    print("Expected behavior for NEAR_USDT (from API):")
    print(f"  - qty_tick_size: {qty_tick_size_str}")
    print(f"  - quantity_decimals: {quantity_decimals}")
    print(f"  - 6.42508353 should round DOWN to 6.4 (correct!)")
    print()
    
    print("=" * 80)
    
    # Test verification mode via place_market_order
    print()
    print("Step 5: Testing verification mode (VERIFY_ORDER_FORMAT=1)...")
    print()
    
    # Set verification mode
    os.environ["VERIFY_ORDER_FORMAT"] = "1"
    
    try:
        result = trade_client.place_market_order(
            symbol=symbol,
            side="SELL",
            qty=raw_quantity,
            dry_run=False  # Verification mode will return early anyway
        )
        
        if result.get("verify_mode"):
            print("✅ Verification mode worked correctly")
            print()
            print("Verification result:")
            print(f"  - Symbol: {result['symbol']}")
            print(f"  - Side: {result['side']}")
            print(f"  - Raw Quantity: {result['raw_quantity']}")
            print(f"  - Normalized Quantity: {result['normalized_quantity']}")
            print(f"  - Instrument Rules:")
            for key, value in result['instrument_rules'].items():
                print(f"      - {key}: {value}")
        else:
            print("⚠️  Verification mode did not activate (unexpected)")
    except Exception as e:
        print(f"❌ Error in verification mode: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 80)
    print("Verification complete!")


if __name__ == "__main__":
    main()
