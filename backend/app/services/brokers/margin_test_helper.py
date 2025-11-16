#!/usr/bin/env python3
"""
Margin Test Helper for Crypto.com Exchange API

This helper function allows testing small margin orders to verify
that the margin order request construction is correct.

WARNING: This is for debugging only. Do NOT call in production automatically.
Use only via a protected /debug endpoint or manual testing.
"""

import logging
from typing import Dict, Optional
from app.services.brokers.crypto_com_trade import CryptoComTradeClient

logger = logging.getLogger(__name__)


def test_margin_order(
    symbol: str = "BTC_USDT",
    side: str = "BUY",
    order_type: str = "MARKET",
    notional: float = 20.0,
    leverage: int = 10,
    dry_run: bool = True
) -> Dict:
    """
    Test margin order construction and sending.
    
    This function uses the same internal builder as production margin orders,
    allowing us to verify the request payload matches Crypto.com API requirements.
    
    Args:
        symbol: Trading symbol (e.g., "BTC_USDT", "DOGE_USDT")
        side: "BUY" or "SELL"
        order_type: "MARKET" or "LIMIT" (MARKET recommended for testing)
        notional: Amount in quote currency (e.g., USDT) - use small amounts like 20 USD
        leverage: Leverage multiplier (typically 10)
        dry_run: If True, doesn't place real order
    
    Returns:
        Dict with order result or error details
    
    Example usage:
        result = test_margin_order(symbol="DOGE_USDT", notional=20.0, dry_run=False)
    """
    trade_client = CryptoComTradeClient()
    
    logger.info(f"[MARGIN_TEST] Starting margin order test")
    logger.info(f"[MARGIN_TEST] symbol={symbol} side={side} type={order_type}")
    logger.info(f"[MARGIN_TEST] notional={notional} leverage={leverage} dry_run={dry_run}")
    
    try:
        if order_type.upper() == "MARKET":
            if side.upper() == "BUY":
                result = trade_client.place_market_order(
                    symbol=symbol,
                    side=side,
                    notional=notional,
                    is_margin=True,
                    leverage=leverage,
                    dry_run=dry_run
                )
            else:  # SELL
                # For SELL orders, we need quantity, not notional
                # This is a limitation - we'd need current price to calculate quantity
                logger.error(f"[MARGIN_TEST] SELL orders require quantity, not notional. Skipping test.")
                return {
                    "error": "SELL orders require quantity parameter, not notional",
                    "suggestion": "Use BUY orders for testing, or provide quantity for SELL"
                }
        else:  # LIMIT
            # For LIMIT orders, we need price and quantity
            logger.error(f"[MARGIN_TEST] LIMIT orders require price and quantity. Use MARKET for testing.")
            return {
                "error": "LIMIT orders require price and quantity parameters",
                "suggestion": "Use order_type='MARKET' for testing"
            }
        
        # Log the test result
        if "error" in result:
            logger.error(f"[MARGIN_TEST] FAILED: {result.get('error')}")
            logger.error(f"[MARGIN_TEST] result={result}")
        else:
            logger.info(f"[MARGIN_TEST] SUCCESS: order_id={result.get('order_id', 'N/A')}")
            logger.info(f"[MARGIN_TEST] result={result}")
        
        return result
        
    except Exception as e:
        logger.error(f"[MARGIN_TEST] EXCEPTION: {e}", exc_info=True)
        return {
            "error": str(e),
            "exception_type": type(e).__name__
        }

