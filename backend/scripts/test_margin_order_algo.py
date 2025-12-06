#!/usr/bin/env python3
"""
Test script to place a minimal margin MARKET BUY order for ALGO_USDT.
This script uses the same authenticated HTTP client as the bot to find
a combination of parameters that works with Crypto.com API.

Once we find the working payload, we'll compare it with the failing bot payload
to identify what needs to be fixed.
"""
import sys
import os
import logging
import json

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.brokers.crypto_com_trade import trade_client
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Constants - same as bot uses
DESIRED_SYMBOL = "ALGO_USDT"
DESIRED_SIDE = "BUY"
DESIRED_LEVERAGE = 2  # Start with 2x as bot does

def get_desired_notional():
    """Get the desired notional from the watchlist item for ALGO_USDT"""
    db = SessionLocal()
    try:
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == DESIRED_SYMBOL
        ).first()
        
        if watchlist_item and watchlist_item.trade_amount_usd:
            notional = watchlist_item.trade_amount_usd
            logger.info(f"Found trade_amount_usd={notional} for {DESIRED_SYMBOL} in watchlist")
            return notional
        else:
            # Default to $1000 if not found
            logger.warning(f"No trade_amount_usd found for {DESIRED_SYMBOL}, using default $1000")
            return 1000.0
    except Exception as e:
        logger.error(f"Error getting desired notional: {e}")
        return 1000.0
    finally:
        db.close()

def test_margin_order():
    """Test placing a margin MARKET BUY order for ALGO_USDT"""
    notional = get_desired_notional()
    
    logger.info("=" * 80)
    logger.info("TEST: Placing margin MARKET BUY order for ALGO_USDT")
    logger.info("=" * 80)
    logger.info(f"Symbol: {DESIRED_SYMBOL}")
    logger.info(f"Side: {DESIRED_SIDE}")
    logger.info(f"Notional: ${notional:,.2f}")
    logger.info(f"Leverage: {DESIRED_LEVERAGE}x")
    logger.info("=" * 80)
    
    try:
        # Place the order using the same client as the bot
        # This will log [ENTRY_ORDER][TEST] which we can capture
        result = trade_client.place_market_order(
            symbol=DESIRED_SYMBOL,
            side=DESIRED_SIDE,
            notional=notional,
            is_margin=True,
            leverage=DESIRED_LEVERAGE,
            dry_run=False,  # Use actual trading
            source="TEST"  # Mark as test script for logging
        )
        
        logger.info("=" * 80)
        logger.info("RESULT:")
        logger.info("=" * 80)
        logger.info(json.dumps(result, indent=2, ensure_ascii=False))
        logger.info("=" * 80)
        
        if "error" in result:
            logger.error(f"❌ Order failed: {result['error']}")
            return False
        else:
            logger.info("✅ Order placed successfully!")
            logger.info(f"Order ID: {result.get('order_id', 'N/A')}")
            return True
            
    except Exception as e:
        logger.error(f"❌ Exception during order placement: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_margin_order()
    sys.exit(0 if success else 1)

