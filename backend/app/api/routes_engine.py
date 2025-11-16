from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.deps.auth import get_current_user
from app.database import get_db
from app.models.watchlist import WatchlistItem
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/engine/run-once")
def run_engine_once(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Run the trading engine once"""
    try:
        # Get all pending watchlist items
        items = db.query(WatchlistItem).filter(
            WatchlistItem.order_status == "PENDING"
        ).all()
        
        filled = []
        rejected = []
        
        # Mock engine logic - in a real implementation, this would:
        # 1. Fetch current market data for each symbol
        # 2. Calculate indicators (RSI, MA, etc.)
        # 3. Check signals (buy/sell conditions)
        # 4. Place orders if conditions are met
        
        for item in items:
            try:
                # Mock: simulate checking signals and placing orders
                # In reality, this would call the trading client
                logger.info(f"Processing {item.symbol} on {item.exchange}")
                
                # For now, just mark as processed (not implemented)
                filled.append({
                    "symbol": item.symbol,
                    "exchange": item.exchange,
                    "status": "pending_implementation"
                })
            except Exception as e:
                logger.error(f"Error processing {item.symbol}: {e}")
                rejected.append({
                    "symbol": item.symbol,
                    "exchange": item.exchange,
                    "error": str(e)
                })
        
        logger.info(f"Engine run completed. Filled: {len(filled)}, Rejected: {len(rejected)}")
        
        return {
            "filled": filled,
            "rejected": rejected,
            "message": "Engine execution completed"
        }
    except Exception as e:
        logger.error(f"Error running engine: {e}")
        raise HTTPException(status_code=500, detail=str(e))

