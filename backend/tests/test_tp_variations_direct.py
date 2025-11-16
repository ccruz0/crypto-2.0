#!/usr/bin/env python3
"""
Test script to isolate error 220 INVALID_SIDE by testing TP order payload variations directly.
This bypasses the internal variation logic and tests each payload individually.

VERIFICATION:
1. Run the test:
   docker compose exec backend-aws python3 /app/tests/test_tp_variations_direct.py

2. Check logs:
   docker compose logs backend-aws 2>&1 | grep "[TP_ORDER][TEST]" | tail -100

Expected logs:
- [TP_ORDER][TEST] Trying variation=X
- [TP_ORDER][TEST] variation=X payload={...}
- [TP_ORDER][TEST] variation=X response={...}
"""
import sys
import os
import json
import requests
import uuid
sys.path.insert(0, '/app')

# IMPORTANT: Setup logging BEFORE importing any modules that use logging
from app.core.logging_config import setup_logging, get_tp_logger

# Configure logging to ensure logs appear in Docker
setup_logging()

# Get dedicated TP logger for test verification
logger = get_tp_logger()

from app.services.brokers.crypto_com_trade import trade_client
from app.services.brokers.crypto_com_constants import REST_BASE

def create_payload_variations(symbol, tp_price, quantity, ref_price, closing_side):
    """
    Create all payload variations to test directly.
    
    Returns:
        List of dicts with params for the API call
    """
    variations = []
    
    # Format prices
    tp_price_str = f"{tp_price:.4f}".rstrip('0').rstrip('.')
    ref_price_str = f"{ref_price:.6f}".rstrip('0').rstrip('.')
    
    # Base params (required)
    base_params = {
        "instrument_name": symbol,
        "type": "TAKE_PROFIT_LIMIT",
        "price": tp_price_str,
        "quantity": str(quantity),
        "trigger_price": tp_price_str,
        "ref_price": ref_price_str,
        "trigger_condition": f">= {tp_price_str}",
    }
    
    # Variation 1: Minimal with side=SELL
    var1 = base_params.copy()
    var1["side"] = "SELL"
    variations.append({
        "name": "minimal_with_side_SELL",
        "params": var1
    })
    
    # Variation 2: With client_oid and side=SELL
    var2 = base_params.copy()
    var2["side"] = "SELL"
    var2["client_oid"] = str(uuid.uuid4())
    variations.append({
        "name": "with_client_oid_and_side_SELL",
        "params": var2
    })
    
    # Variation 3: With time_in_force and side=SELL
    var3 = base_params.copy()
    var3["side"] = "SELL"
    var3["time_in_force"] = "GOOD_TILL_CANCEL"
    variations.append({
        "name": "with_time_in_force_and_side_SELL",
        "params": var3
    })
    
    # Variation 4: All params with side=SELL
    var4 = base_params.copy()
    var4["side"] = "SELL"
    var4["client_oid"] = str(uuid.uuid4())
    var4["time_in_force"] = "GOOD_TILL_CANCEL"
    variations.append({
        "name": "all_params_with_side_SELL",
        "params": var4
    })
    
    # Variation 5: Minimal WITHOUT side
    var5 = base_params.copy()
    # No side field
    variations.append({
        "name": "minimal_without_side",
        "params": var5
    })
    
    # Variation 6: With client_oid WITHOUT side
    var6 = base_params.copy()
    var6["client_oid"] = str(uuid.uuid4())
    # No side field
    variations.append({
        "name": "with_client_oid_without_side",
        "params": var6
    })
    
    # Variation 7: With time_in_force WITHOUT side
    var7 = base_params.copy()
    var7["time_in_force"] = "GOOD_TILL_CANCEL"
    # No side field
    variations.append({
        "name": "with_time_in_force_without_side",
        "params": var7
    })
    
    # Variation 8: All params WITHOUT side
    var8 = base_params.copy()
    var8["client_oid"] = str(uuid.uuid4())
    var8["time_in_force"] = "GOOD_TILL_CANCEL"
    # No side field
    variations.append({
        "name": "all_params_without_side",
        "params": var8
    })
    
    return variations

def test_single_variation_direct(variation_num, variation):
    """
    Test a single variation by sending the request directly to Crypto.com API.
    
    Returns:
        Dict with 'success', 'error', 'error_code', 'response', 'status_code', 'variation_num', 'variation_name'
    """
    variation_name = variation["name"]
    params = variation["params"]
    
    logger.info(f"[TP_ORDER][TEST] =========================================")
    logger.info(f"[TP_ORDER][TEST] Trying variation={variation_num} ({variation_name})")
    
    # Log key payload fields explicitly before sending
    logger.info(f"[TP_ORDER][TEST] variation={variation_num} payload fields:")
    logger.info(f"[TP_ORDER][TEST]   type: {params.get('type', 'MISSING')}")
    logger.info(f"[TP_ORDER][TEST]   side: {params.get('side', 'MISSING (omitted)')}")
    logger.info(f"[TP_ORDER][TEST]   price: {params.get('price', 'MISSING')}")
    logger.info(f"[TP_ORDER][TEST]   ref_price: {params.get('ref_price', 'MISSING')}")
    logger.info(f"[TP_ORDER][TEST]   instrument_name: {params.get('instrument_name', 'MISSING')}")
    logger.info(f"[TP_ORDER][TEST]   trigger_price: {params.get('trigger_price', 'MISSING')}")
    logger.info(f"[TP_ORDER][TEST]   quantity: {params.get('quantity', 'MISSING')}")
    logger.info(f"[TP_ORDER][TEST] Full payload params: {json.dumps(params, indent=2, ensure_ascii=False)}")
    
    try:
        # Sign the request using trade_client's sign_request method
        method = "private/create-order"
        payload = trade_client.sign_request(method, params)
        
        logger.info(f"[TP_ORDER][TEST] variation={variation_num} Signed payload (with auth): {json.dumps(payload, indent=2, ensure_ascii=False)}")
        
        # Send request directly
        url = f"{trade_client.base_url}/{method}"
        logger.info(f"[TP_ORDER][TEST] variation={variation_num} Sending POST to: {url}")
        
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        status_code = response.status_code
        logger.info(f"[TP_ORDER][TEST] variation={variation_num} HTTP Status: {status_code}")
        
        # Parse response
        try:
            response_data = response.json()
        except:
            response_data = {"raw_text": response.text}
        
        # Log response with key fields
        logger.info(f"[TP_ORDER][TEST] variation={variation_num} response:")
        if "code" in response_data:
            logger.info(f"[TP_ORDER][TEST]   code: {response_data.get('code')}")
        if "message" in response_data:
            logger.info(f"[TP_ORDER][TEST]   message: {response_data.get('message')}")
        if "result" in response_data:
            result = response_data.get("result", {})
            if "order_id" in result:
                logger.info(f"[TP_ORDER][TEST]   order_id: {result.get('order_id')}")
            if "client_oid" in result:
                logger.info(f"[TP_ORDER][TEST]   client_oid: {result.get('client_oid')}")
        logger.info(f"[TP_ORDER][TEST] Full response: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
        
        # Check if successful
        if status_code == 200:
            # Check for error in response body
            if "code" in response_data and response_data.get("code") != 0:
                error_code = response_data.get("code")
                error_msg = response_data.get("message", "Unknown error")
                logger.warning(f"[TP_ORDER][TEST] variation={variation_num} FAILED: Error {error_code}: {error_msg}")
                return {
                    "success": False,
                    "error": f"Error {error_code}: {error_msg}",
                    "error_code": error_code,
                    "response": response_data,
                    "status_code": status_code,
                    "variation_num": variation_num,
                    "variation_name": variation_name
                }
            else:
                # Success!
                order_id = response_data.get("result", {}).get("order_id") or response_data.get("result", {}).get("client_oid")
                logger.info(f"[TP_ORDER][TEST] variation={variation_num} SUCCESS! order_id={order_id}")
                return {
                    "success": True,
                    "order_id": order_id,
                    "response": response_data,
                    "status_code": status_code,
                    "variation_num": variation_num,
                    "variation_name": variation_name
                }
        else:
            # HTTP error
            error_code = response_data.get("code", status_code)
            error_msg = response_data.get("message", f"HTTP {status_code}")
            logger.warning(f"[TP_ORDER][TEST] variation={variation_num} FAILED: HTTP {status_code}, Error {error_code}: {error_msg}")
            return {
                "success": False,
                "error": f"HTTP {status_code}: {error_msg}",
                "error_code": error_code,
                "response": response_data,
                "status_code": status_code,
                "variation_num": variation_num,
                "variation_name": variation_name
            }
            
    except Exception as e:
        logger.error(f"[TP_ORDER][TEST] variation={variation_num} EXCEPTION: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "response": None,
            "status_code": None,
            "variation_num": variation_num,
            "variation_name": variation_name
        }

def summarize_results(results):
    """
    Analyze and summarize test results by error codes.
    
    Args:
        results: List of result dicts from test_single_variation_direct
    """
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    # Categorize results
    successful = [r for r in results if r.get("success")]
    
    # Group failures by error code
    error_groups = {}
    for r in results:
        if not r.get("success"):
            error_code = r.get("error_code")
            if error_code:
                if error_code not in error_groups:
                    error_groups[error_code] = []
                error_groups[error_code].append(r)
            else:
                # Unknown error code
                if "unknown" not in error_groups:
                    error_groups["unknown"] = []
                error_groups["unknown"].append(r)
    
    # Print successful variations
    print(f"\n✅ Successful variations: {len(successful)}")
    if successful:
        for r in successful:
            print(f"   - Variation {r.get('variation_num')} ({r.get('variation_name')}): order_id={r.get('order_id')}")
    else:
        print("   None")
    
    # Print failures grouped by error code
    if error_groups:
        print(f"\n❌ Failed variations by error code:")
        
        # Error 229 (INVALID_REF_PRICE)
        if 229 in error_groups:
            failed_229 = error_groups[229]
            print(f"\n   Error 229 (INVALID_REF_PRICE): {len(failed_229)} variation(s)")
            for r in failed_229:
                print(f"      - Variation {r.get('variation_num')} ({r.get('variation_name')})")
                error_msg = r.get("error", "Unknown")
                print(f"        Error: {error_msg}")
        
        # Error 40004 (Missing or invalid argument)
        if 40004 in error_groups:
            failed_40004 = error_groups[40004]
            print(f"\n   Error 40004 (Missing or invalid argument): {len(failed_40004)} variation(s)")
            for r in failed_40004:
                print(f"      - Variation {r.get('variation_num')} ({r.get('variation_name')})")
                error_msg = r.get("error", "Unknown")
                print(f"        Error: {error_msg}")
        
        # Error 220 (INVALID_SIDE)
        if 220 in error_groups:
            failed_220 = error_groups[220]
            print(f"\n   Error 220 (INVALID_SIDE): {len(failed_220)} variation(s)")
            for r in failed_220:
                print(f"      - Variation {r.get('variation_num')} ({r.get('variation_name')})")
                error_msg = r.get("error", "Unknown")
                print(f"        Error: {error_msg}")
        
        # Other error codes
        other_errors = {k: v for k, v in error_groups.items() if k not in [229, 40004, 220, "unknown"]}
        if other_errors:
            print(f"\n   Other errors:")
            for error_code, failed_list in other_errors.items():
                print(f"      Error {error_code}: {len(failed_list)} variation(s)")
                for r in failed_list:
                    print(f"         - Variation {r.get('variation_num')} ({r.get('variation_name')})")
                    error_msg = r.get("error", "Unknown")
                    print(f"           Error: {error_msg}")
        
        # Unknown errors
        if "unknown" in error_groups:
            failed_unknown = error_groups["unknown"]
            print(f"\n   Unknown errors: {len(failed_unknown)} variation(s)")
            for r in failed_unknown:
                print(f"      - Variation {r.get('variation_num')} ({r.get('variation_name')})")
                error_msg = r.get("error", "Unknown")
                print(f"        Error: {error_msg}")
    
    # Analysis and recommendations
    if not successful:
        print("\n⚠️  All variations failed")
        
        # Analyze patterns
        has_229 = 229 in error_groups
        has_40004 = 40004 in error_groups
        has_220 = 220 in error_groups
        
        if has_229 and has_40004:
            print("\n   Analysis:")
            print("   - Variations with 'side' field → Error 229 (INVALID_REF_PRICE)")
            print("   - Variations without 'side' field → Error 40004 (Missing/invalid argument)")
            print("\n   Possible causes:")
            print("   1. Error 229: ref_price format/value is incorrect for TAKE_PROFIT_LIMIT")
            print("   2. Error 40004: Crypto.com requires 'side' field for TAKE_PROFIT_LIMIT")
            print("\n   Next steps:")
            print("   1. Review ref_price calculation - ensure it's correct for the order type")
            print("   2. Check if 'side' field is required (error 40004 suggests it is)")
            print("   3. Verify ref_price is on the correct side of market (SELL: ref_price < market)")
        
        elif has_229:
            print("\n   Analysis:")
            print("   - All failures are Error 229 (INVALID_REF_PRICE)")
            print("\n   Possible causes:")
            print("   1. ref_price format is incorrect")
            print("   2. ref_price value doesn't match Crypto.com requirements")
            print("   3. ref_price must be on correct side of market (SELL: ref_price < market price)")
            print("\n   Next steps:")
            print("   1. Review ref_price calculation logic")
            print("   2. Check Crypto.com API documentation for ref_price requirements")
            print("   3. Compare ref_price with successful orders in history")
        
        elif has_40004:
            print("\n   Analysis:")
            print("   - All failures are Error 40004 (Missing or invalid argument)")
            print("\n   Possible causes:")
            print("   1. Missing required field (likely 'side')")
            print("   2. Field format is incorrect")
            print("   3. Crypto.com cannot infer 'side' automatically")
            print("\n   Next steps:")
            print("   1. Ensure 'side' field is included in payload")
            print("   2. Verify 'side' format is correct (uppercase: SELL/BUY)")
            print("   3. Check if position must be open for Crypto.com to infer 'side'")
        
        elif has_220:
            print("\n   Analysis:")
            print("   - All failures are Error 220 (INVALID_SIDE)")
            print("\n   Possible causes:")
            print("   1. No open position for AKT_USDT")
            print("   2. Side field doesn't match the position direction")
            print("   3. Crypto.com requires side to match the position")
            print("\n   Next steps:")
            print("   1. Check if there's an open BUY position for AKT_USDT")
            print("   2. Try creating a small BUY order first to open a position")
            print("   3. Verify the side matches the position direction (BUY position → SELL for TP)")

def main():
    """Test TP order variations directly"""
    print("="*80)
    print("TESTING TP ORDER VARIATIONS DIRECTLY (Error 220 Isolation)")
    print("="*80)
    print("\nParameters:")
    print("  symbol: AKT_USDT")
    print("  entry_side: BUY (original order side)")
    print("  closing_side: SELL (for TP order)")
    print("  tp_price: 1.5632")
    print("  quantity: 6.5")
    print("  entry_price: 1.5177")
    print("  ref_price: ~0.64 (calculated from market price)")
    print("  source: manual")
    print("  dry_run: False (LIVE TRADING)")
    print("\n" + "="*80)
    print("Testing variations individually...")
    print("="*80 + "\n")
    
    # Sanity check
    logger.info("[TP_ORDER][TEST] Sanity check log before testing variations")
    print("✅ Test logger configured - check logs for [TP_ORDER][TEST]")
    
    # Get current market price for ref_price calculation
    try:
        import requests as req_module
        ticker_url = "https://api.crypto.com/v2/public/get-ticker"
        ticker_params = {"instrument_name": "AKT_USDT"}
        ticker_response = req_module.get(ticker_url, params=ticker_params, timeout=5)
        if ticker_response.status_code == 200:
            ticker_data = ticker_response.json()
            result_data = ticker_data.get("result", {})
            if "data" in result_data and len(result_data["data"]) > 0:
                ticker_item = result_data["data"][0]
                market_price = float(ticker_item.get("a", 0))  # Ask price
                # Calculate ref_price: for SELL, must be < market price
                ref_price = round(market_price * 0.995, 6)
                print(f"✅ Got market price: {market_price}, calculated ref_price: {ref_price}")
            else:
                ref_price = 0.64  # Fallback
                print(f"⚠️  Using fallback ref_price: {ref_price}")
        else:
            ref_price = 0.64  # Fallback
            print(f"⚠️  Using fallback ref_price: {ref_price}")
    except Exception as e:
        ref_price = 0.64  # Fallback
        print(f"⚠️  Error getting market price: {e}, using fallback ref_price: {ref_price}")
    
    # Create variations
    variations = create_payload_variations(
        symbol="AKT_USDT",
        tp_price=1.5632,
        quantity=6.5,
        ref_price=ref_price,
        closing_side="SELL"
    )
    
    print(f"\n📋 Created {len(variations)} variations to test\n")
    
    results = []
    
    # Test each variation individually
    for i, variation in enumerate(variations, start=1):
        print(f"\n{'='*80}")
        print(f"Testing Variation {i}/{len(variations)}: {variation['name']}")
        print(f"{'='*80}\n")
        
        result = test_single_variation_direct(i, variation)
        results.append(result)
        
        # Stop if we find a successful variation
        if result.get("success"):
            print(f"\n✅ SUCCESS! Variation {i} worked!")
            print(f"   Variation name: {result.get('variation_name')}")
            print(f"   Order ID: {result.get('order_id')}")
            print(f"\n⚠️  Stopping tests - found working variation")
            break
        
        # Check if error is NOT 220 (different error, might be worth continuing)
        error_code = result.get("error_code")
        if error_code and error_code != 220:
            print(f"\n⚠️  Variation {i} failed with different error: {error_code}")
            print(f"   This might indicate a different issue")
        
        # Wait a bit between variations to avoid rate limiting
        import time
        time.sleep(2)
    
    # Summary using summarize_results function
    summarize_results(results)
    
    print("\n" + "="*80)
    print("Check detailed logs with:")
    print("  docker compose logs backend-aws 2>&1 | grep '[TP_ORDER][TEST]' | tail -150")
    print("="*80)
    
    return 0

if __name__ == '__main__':
    sys.exit(main())

