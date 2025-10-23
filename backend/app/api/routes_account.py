from fastapi import APIRouter, Depends, HTTPException, Query
from app.deps.auth import get_current_user
from app.services.brokers.crypto_com_trade import trade_client
from app.utils.redact import redact_secrets
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/account/balance")
def get_account_balance(
    exchange: str = Query(..., description="Exchange name"),
    current_user = Depends(get_current_user)
):
    """Get account balance for specified exchange"""
    if exchange != "CRYPTO_COM":
        raise HTTPException(status_code=400, detail="Only CRYPTO_COM supported")
    
    try:
        result = trade_client.get_account_summary()
        logger.info(f"Account balance retrieved for {exchange}")
        logger.debug(f"Response: {redact_secrets(result)}")
        return result
    except Exception as e:
        logger.error(f"Error getting account balance: {e}")
        raise HTTPException(status_code=502, detail=str(e))
