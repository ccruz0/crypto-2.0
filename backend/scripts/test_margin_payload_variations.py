#!/usr/bin/env python3
"""
Test script to automatically try different payload variations for ALGO_USDT margin orders.
Uses the authenticated trade_client to test various parameter combinations.
Stops when it finds a working combination.
"""
import sys
import os
import logging
import json
import time

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.brokers.crypto_com_trade import trade_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DESIRED_SYMBOL = "ALGO_USDT"
DESIRED_SIDE = "BUY"
DESIRED_LEVERAGE = 2
DESIRED_NOTIONAL = 1000.0

def test_variation(variation_name: str, **kwargs):
    """Test a specific payload variation by modifying place_market_order parameters"""
    logger.info("=" * 80)
    logger.info(f"TESTING VARIATION: {variation_name}")
    logger.info("=" * 80)
    
    try:
        # Call place_market_order with the variation parameters
        # source="TEST" so it logs as [ENTRY_ORDER][TEST]
        result = trade_client.place_market_order(
            symbol=DESIRED_SYMBOL,
            side=DESIRED_SIDE,
            **kwargs,
            is_margin=True,
            dry_run=False,
            source="TEST"
        )
        
        logger.info("=" * 80)
        logger.info(f"RESULT for '{variation_name}':")
        logger.info("=" * 80)
        logger.info(json.dumps(result, indent=2, ensure_ascii=False))
        logger.info("=" * 80)
        
        if "error" in result:
            error_code = result.get("error", "")
            if "306" in str(error_code) or "INSUFFICIENT_AVAILABLE_BALANCE" in str(error_code):
                logger.warning(f"❌ Variation '{variation_name}' still failed with error 306")
                return False
            else:
                logger.warning(f"⚠️ Variation '{variation_name}' failed with different error: {error_code}")
                return False
        else:
            logger.info(f"✅ SUCCESS! Variation '{variation_name}' worked!")
            logger.info(f"Order ID: {result.get('order_id', 'N/A')}")
            return True
            
    except Exception as e:
        logger.error(f"❌ Exception during test of '{variation_name}': {e}", exc_info=True)
        return False

def main():
    logger.info("=" * 80)
    logger.info("AUTOMATED PAYLOAD VARIATION TESTING")
    logger.info("=" * 80)
    logger.info(f"Symbol: {DESIRED_SYMBOL}")
    logger.info(f"Side: {DESIRED_SYMBOL}")
    logger.info(f"Notional: ${DESIRED_NOTIONAL:,.2f}")
    logger.info(f"Leverage: {DESIRED_LEVERAGE}x")
    logger.info("=" * 80)
    
    variations = [
        # Variation 1: Current (baseline) - notional as string, leverage as string
        ("1. Baseline (current)", {
            "notional": "1000.00",
            "leverage": "2"
        }),
        
        # Variation 2: leverage as number (float)
        ("2. leverage as float (2.0)", {
            "notional": "1000.00",
            "leverage": 2.0
        }),
        
        # Variation 3: leverage as integer
        ("3. leverage as int (2)", {
            "notional": "1000.00",
            "leverage": 2
        }),
        
        # Variation 4: notional as float
        ("4. notional as float (1000.0)", {
            "notional": 1000.0,
            "leverage": "2"
        }),
        
        # Variation 5: notional as int
        ("5. notional as int (1000)", {
            "notional": 1000,
            "leverage": "2"
        }),
        
        # Variation 6: both as numbers (float)
        ("6. both as float", {
            "notional": 1000.0,
            "leverage": 2.0
        }),
        
        # Variation 7: both as numbers (int)
        ("7. both as int", {
            "notional": 1000,
            "leverage": 2
        }),
        
        # Variation 8: notional with more decimals
        ("8. notional with 4 decimals", {
            "notional": "1000.0000",
            "leverage": "2"
        }),
        
        # Variation 9: leverage without decimals
        ("9. leverage as string '2' no conversion", {
            "notional": "1000.00",
            "leverage": "2"
        }),
        
        # Variation 10: Try quantity instead of notional (need to calculate)
        # For ALGO_USDT at ~$0.38, $1000 = ~2631 ALGO
        ("10. use quantity instead of notional (approx)", {
            "qty": 2631.0,  # Approximate quantity for $1000 at current price
            "leverage": "2"
        }),
    ]
    
    logger.info(f"Testing {len(variations)} variations...")
    logger.info("=" * 80)
    
    working_variation = None
    for name, params in variations:
        success = test_variation(name, **params)
        
        if success:
            working_variation = (name, params)
            logger.info("=" * 80)
            logger.info(f"🎉 FOUND WORKING VARIATION: {name}")
            logger.info(f"Working parameters: {json.dumps(params, indent=2, ensure_ascii=False)}")
            logger.info("=" * 80)
            break
        
        # Small delay between tests to avoid rate limiting
        time.sleep(3)
    
    if working_variation:
        logger.info("=" * 80)
        logger.info("✅ SUCCESS - Found working payload format!")
        logger.info(f"Variation: {working_variation[0]}")
        logger.info(f"Parameters: {json.dumps(working_variation[1], indent=2, ensure_ascii=False)}")
        logger.info("=" * 80)
        logger.info("Next step: Update place_market_order to use this parameter format")
        return True
    else:
        logger.info("=" * 80)
        logger.info("❌ No working variation found")
        logger.info("=" * 80)
        logger.info("All variations failed with error 306 or other errors.")
        logger.info("Possible causes:")
        logger.info("  1. Account truly has insufficient balance (even with 2x leverage)")
        logger.info("  2. ALGO_USDT might have restrictions or not support margin")
        logger.info("  3. Payload format differences might require capturing manual order")
        logger.info("=" * 80)
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

