"""
Debug endpoints for testing margin orders

WARNING: These endpoints are for debugging only.
They should be protected by authentication and not exposed in production.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

from app.services.brokers.margin_test_helper import test_margin_order


@router.post("/debug/test-margin-order")
def debug_test_margin_order(
    symbol: str = Query("BTC_USDT", description="Trading symbol"),
    side: str = Query("BUY", description="BUY or SELL"),
    notional: float = Query(20.0, description="Amount in quote currency (for BUY orders)"),
    leverage: int = Query(10, description="Leverage multiplier"),
    dry_run: bool = Query(True, description="If True, doesn't place real order")
):
    """
    Test margin order construction and sending.
    
    WARNING: This is for debugging only. Do NOT use in production.
    
    This endpoint uses the same internal builder as production margin orders,
    allowing you to verify the request payload matches Crypto.com API requirements.
    
    Example:
        POST /api/debug/test-margin-order?symbol=DOGE_USDT&notional=20&leverage=10&dry_run=false
    """
    try:
        if side.upper() not in ["BUY", "SELL"]:
            raise HTTPException(status_code=400, detail="side must be BUY or SELL")
        
        if notional <= 0:
            raise HTTPException(status_code=400, detail="notional must be positive")
        
        if leverage <= 0 or leverage > 20:
            raise HTTPException(status_code=400, detail="leverage must be between 1 and 20")
        
        result = test_margin_order(
            symbol=symbol.upper(),
            side=side.upper(),
            order_type="MARKET",
            notional=notional,
            leverage=leverage,
            dry_run=dry_run
        )
        
        return {
            "ok": "error" not in result,
            "result": result,
            "note": "Check backend logs for [MARGIN_REQUEST] and [MARGIN_RESPONSE] details"
        }
        
    except Exception as e:
        logger.error(f"Error in debug test margin order: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

