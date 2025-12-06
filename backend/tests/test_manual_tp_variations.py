#!/usr/bin/env python3
"""
Test script to isolate error 220 INVALID_SIDE by testing TP order variations individually.
This allows us to identify which payload variation works with Crypto.com API.

VERIFICATION:
1. Run the test:
   docker compose exec backend-aws python3 /app/tests/test_manual_tp_variations.py

2. Check logs:
   docker compose logs backend-aws 2>&1 | grep "[TP_ORDER][TEST]" | tail -100

Expected logs:
- [TP_ORDER][TEST] Trying variation=X
- [TP_ORDER][TEST] variation=X payload={...}
- [TP_ORDER][TEST] variation=X response={...}
"""
import sys
import os
sys.path.insert(0, '/app')

# IMPORTANT: Setup logging BEFORE importing any modules that use logging
from app.core.logging_config import setup_logging, get_tp_logger

# Configure logging to ensure logs appear in Docker
setup_logging()

# Get dedicated TP logger for test verification
logger = get_tp_logger()

from app.database import SessionLocal
from app.services.brokers.crypto_com_trade import trade_client
import uuid

def create_tp_payload_variations(symbol, tp_price, quantity, entry_price, closing_side):
    """
    Create all payload variations to test.
    
    Returns:
        List of dicts with parameters for place_take_profit_order
    """
    variations = []
    
    # Format prices
    tp_price_str = f"{tp_price:.4f}".rstrip('0').rstrip('.')
    
    # Variation set 1: WITH side field (closing side)
    variations.append({
        "symbol": symbol,
        "side": closing_side,  # SELL for BUY entry
        "price": tp_price,
        "qty": quantity,
        "trigger_price": tp_price,
        "entry_price": entry_price,
        "dry_run": False,
        "source": "manual",
        "variation_name": "with_side_minimal"
    })
    
    variations.append({
        "symbol": symbol,
        "side": closing_side,
        "price": tp_price,
        "qty": quantity,
        "trigger_price": tp_price,
        "entry_price": entry_price,
        "dry_run": False,
        "source": "manual",
        "variation_name": "with_side_all_params"
    })
    
    # Variation set 2: Try with different side values
    # Note: These might fail, but we want to test them
    variations.append({
        "symbol": symbol,
        "side": closing_side.lower(),  # lowercase
        "price": tp_price,
        "qty": quantity,
        "trigger_price": tp_price,
        "entry_price": entry_price,
        "dry_run": False,
        "source": "manual",
        "variation_name": "with_side_lowercase"
    })
    
    # Variation set 3: WITHOUT explicit side (let Crypto.com infer)
    # We'll need to modify place_take_profit_order to accept None for side
    # For now, we'll test with the current implementation
    
    return variations

def test_single_variation(variation_num, variation_params):
    """
    Test a single variation and log the results.
    
    Returns:
        Dict with 'success', 'error', 'response'
    """
    variation_name = variation_params.pop("variation_name", f"variation_{variation_num}")
    
    logger.info(f"[TP_ORDER][TEST] =========================================")
    logger.info(f"[TP_ORDER][TEST] Trying variation={variation_num} ({variation_name})")
    logger.info(f"[TP_ORDER][TEST] Payload params: {variation_params}")
    
    try:
        # Call place_take_profit_order
        response = trade_client.place_take_profit_order(**variation_params)
        
        logger.info(f"[TP_ORDER][TEST] variation={variation_num} response: {response}")
        
        # Check if successful
        if "error" in response:
            error_msg = response.get("error", "Unknown error")
            logger.warning(f"[TP_ORDER][TEST] variation={variation_num} FAILED: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "response": response,
                "variation_num": variation_num,
                "variation_name": variation_name
            }
        else:
            order_id = response.get("order_id") or response.get("client_order_id")
            logger.info(f"[TP_ORDER][TEST] variation={variation_num} SUCCESS! order_id={order_id}")
            return {
                "success": True,
                "order_id": order_id,
                "response": response,
                "variation_num": variation_num,
                "variation_name": variation_name
            }
            
    except Exception as e:
        logger.error(f"[TP_ORDER][TEST] variation={variation_num} EXCEPTION: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "response": None,
            "variation_num": variation_num,
            "variation_name": variation_name
        }

def main():
    """Test manual TP creation with individual variations"""
    db = SessionLocal()
    
    try:
        print("="*80)
        print("TESTING TP ORDER VARIATIONS (Error 220 Isolation)")
        print("="*80)
        print("\nParameters:")
        print("  symbol: AKT_USDT")
        print("  entry_side: BUY (original order side)")
        print("  closing_side: SELL (for TP order)")
        print("  tp_price: 1.5632")
        print("  quantity: 6.5")
        print("  entry_price: 1.5177")
        print("  source: manual")
        print("  dry_run: False (LIVE TRADING)")
        print("\n" + "="*80)
        print("Testing variations individually...")
        print("="*80 + "\n")
        
        # Sanity check: Log before placing TP order to verify logging works
        logger.info("[TP_ORDER][TEST] Sanity check log before testing variations")
        print("✅ Test logger configured - check logs for [TP_ORDER][TEST]")
        
        # Create variations
        variations = create_tp_payload_variations(
            symbol="AKT_USDT",
            tp_price=1.5632,
            quantity=6.5,
            entry_price=1.5177,
            closing_side="SELL"  # Closing side for BUY entry
        )
        
        print(f"\n📋 Created {len(variations)} variations to test\n")
        
        results = []
        
        # Test each variation individually
        for i, variation_params in enumerate(variations, start=1):
            print(f"\n{'='*80}")
            print(f"Testing Variation {i}/{len(variations)}")
            print(f"{'='*80}\n")
            
            result = test_single_variation(i, variation_params.copy())
            results.append(result)
            
            # Stop if we find a successful variation
            if result.get("success"):
                print(f"\n✅ SUCCESS! Variation {i} worked!")
                print(f"   Variation name: {result.get('variation_name')}")
                print(f"   Order ID: {result.get('order_id')}")
                break
            
            # Wait a bit between variations to avoid rate limiting
            import time
            time.sleep(1)
        
        # Summary
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        successful = [r for r in results if r.get("success")]
        failed = [r for r in results if not r.get("success")]
        
        print(f"\n✅ Successful variations: {len(successful)}")
        for r in successful:
            print(f"   - Variation {r.get('variation_num')} ({r.get('variation_name')}): order_id={r.get('order_id')}")
        
        print(f"\n❌ Failed variations: {len(failed)}")
        for r in failed:
            error = r.get("error", "Unknown")
            print(f"   - Variation {r.get('variation_num')} ({r.get('variation_name')}): {error}")
        
        if not successful:
            print("\n⚠️  All variations failed with error 220 INVALID_SIDE")
            print("   Next steps:")
            print("   1. Check if there's an open position for AKT_USDT")
            print("   2. Try creating a small BUY order first to open a position")
            print("   3. Review the exact payloads sent in the logs")
        
        print("\n" + "="*80)
        print("Check detailed logs with:")
        print("  docker compose logs backend-aws 2>&1 | grep '[TP_ORDER][TEST]' | tail -100")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()
    
    return 0

if __name__ == '__main__':
    sys.exit(main())

