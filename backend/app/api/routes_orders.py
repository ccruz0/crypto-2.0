from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from typing import Optional
from app.deps.auth import get_current_user
from app.services.brokers.crypto_com_trade import trade_client
from app.utils.redact import redact_secrets
import logging
import os

logger = logging.getLogger(__name__)
router = APIRouter()

class PlaceOrderRequest(BaseModel):
    exchange: str
    symbol: str
    side: str  # BUY or SELL
    type: str  # MARKET or LIMIT
    qty: float
    price: Optional[float] = None

class CancelOrderRequest(BaseModel):
    exchange: str
    order_id: Optional[str] = None
    client_oid: Optional[str] = None

@router.post("/orders/place")
def place_order(
    request: PlaceOrderRequest,
    current_user = Depends(get_current_user)
):
    """Place order on specified exchange"""
    if request.exchange != "CRYPTO_COM":
        raise HTTPException(status_code=400, detail="Only CRYPTO_COM supported")
    
    live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
    
    try:
        if request.type == "MARKET":
            result = trade_client.place_market_order(
                request.symbol,
                request.side,
                request.qty,
                dry_run=not live_trading
            )
        elif request.type == "LIMIT":
            if not request.price:
                raise HTTPException(status_code=400, detail="Price required for LIMIT orders")
            result = trade_client.place_limit_order(
                request.symbol,
                request.side,
                request.price,
                request.qty,
                dry_run=not live_trading
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid order type")
        
        logger.info(f"Order placed: {request.symbol} {request.side} {request.type} qty={request.qty}")
        logger.debug(f"Response: {redact_secrets(result)}")
        return result
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        raise HTTPException(status_code=502, detail=str(e))

@router.post("/orders/cancel")
def cancel_order(
    request: CancelOrderRequest,
    current_user = Depends(get_current_user)
):
    """Cancel order on specified exchange"""
    if request.exchange != "CRYPTO_COM":
        raise HTTPException(status_code=400, detail="Only CRYPTO_COM supported")
    
    if not request.order_id and not request.client_oid:
        raise HTTPException(status_code=400, detail="order_id or client_oid required")
    
    try:
        order_id = request.order_id or request.client_oid
        result = trade_client.cancel_order(order_id)
        logger.info(f"Order cancelled: {order_id}")
        return result
    except Exception as e:
        logger.error(f"Error cancelling order: {e}")
        raise HTTPException(status_code=502, detail=str(e))
