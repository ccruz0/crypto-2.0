"""Ultra-simplified dashboard state endpoint - returns empty data immediately"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
import logging
import time

router = APIRouter()
log = logging.getLogger("app.dashboard")

@router.get("/dashboard/state")
def get_dashboard_state(db: Session = Depends(get_db)):
    """
    Ultra-simplified dashboard state endpoint
    Returns empty data immediately to prevent timeout
    """
    start_time = time.time()
    log.info("Starting dashboard state fetch (ultra-simplified)")
    
    elapsed = time.time() - start_time
    log.info(f"✅ Dashboard state returned in {elapsed:.3f}s")
    
    return {
        "source": "simplified",
        "total_usd_value": 0.0,
        "balances": [],
        "fast_signals": [],
        "slow_signals": [],
        "open_orders": [],
        "last_sync": None,
        "portfolio_last_updated": None,
        "portfolio": {
            "assets": [],
            "total_value_usd": 0.0,
            "exchange": "Crypto.com Exchange"
        },
        "bot_status": {
            "is_running": True,
            "status": "running",
            "reason": None
        },
        "partial": True,
        "errors": ["simplified_mode"]
    }
