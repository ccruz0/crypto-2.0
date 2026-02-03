"""
Admin-only API endpoints
Requires X-Admin-Key header matching ADMIN_ACTIONS_KEY env var
"""
import os
import logging
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Header, HTTPException, Depends, Body
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.telegram_notifier import telegram_notifier
from app.services.system_health import record_telegram_send_result
from app.services.signal_monitor import signal_monitor_service
from app.models.watchlist_master import WatchlistItem

router = APIRouter()


class EvaluateSymbolBody(BaseModel):
    symbol: str = "BTC_USDT"
logger = logging.getLogger(__name__)

# Rate limiting: last test timestamp (in-memory, per-process)
_last_test_telegram_ts: Optional[float] = None
_TEST_TELEGRAM_COOLDOWN_SECONDS = 60

def verify_admin_key(x_admin_key: Optional[str] = Header(None)) -> str:
    """Verify admin key from header"""
    expected_key = os.getenv("ADMIN_ACTIONS_KEY")
    
    if not expected_key:
        logger.warning("ADMIN_ACTIONS_KEY not set - admin endpoints disabled")
        raise HTTPException(status_code=401, detail="Admin actions not configured")
    
    if not x_admin_key or x_admin_key != expected_key:
        logger.warning(f"Invalid admin key attempt (header present: {x_admin_key is not None})")
        raise HTTPException(status_code=401, detail="unauthorized")
    
    return x_admin_key

@router.post("/admin/test-telegram")
async def test_telegram(
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """
    Send a test Telegram message (admin-only, rate-limited)
    
    Requires:
    - Header: X-Admin-Key: <ADMIN_ACTIONS_KEY>
    
    Returns:
    - {"ok": true} on success
    - {"ok": false, "error": "<reason>"} on failure
    """
    global _last_test_telegram_ts
    
    # Rate limiting check
    now = time.time()
    if _last_test_telegram_ts is not None:
        time_since_last = now - _last_test_telegram_ts
        if time_since_last < _TEST_TELEGRAM_COOLDOWN_SECONDS:
            remaining = int(_TEST_TELEGRAM_COOLDOWN_SECONDS - time_since_last)
            logger.warning(f"Test telegram rate limited (cooldown: {remaining}s remaining)")
            raise HTTPException(
                status_code=429,
                detail=f"rate_limited (cooldown: {remaining}s remaining)"
            )
    
    try:
        # Send test message
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        message = f"✅ TEST: Telegram is working (AWS) — {timestamp}"
        
        if not telegram_notifier.enabled:
            return {"ok": False, "error": "telegram_disabled"}
        
        success = telegram_notifier.send_message(message, origin="AWS")
        record_telegram_send_result(success)
        
        if success:
            _last_test_telegram_ts = now
            logger.info("Test Telegram message sent successfully")
            return {"ok": True}
        else:
            return {"ok": False, "error": "send_failed"}
    
    except Exception as e:
        logger.error(f"Error sending test Telegram message: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


@router.post("/admin/debug/evaluate-symbol")
def evaluate_symbol(
    body: EvaluateSymbolBody = Body(...),
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """
    Trigger signal evaluation for one symbol (admin-only, for smoke/E2E).
    Requires X-Admin-Key header. Writes to watchlist_signal_state and may send Telegram.
    """
    symbol = (body.symbol or "BTC_USDT").strip().upper()
    try:
        watchlist_item = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.symbol == symbol, WatchlistItem.is_deleted == False)
            .first()
        )
        if not watchlist_item:
            return {"ok": False, "error": f"symbol_not_in_watchlist:{symbol}"}
        signal_monitor_service._check_signal_for_coin_sync(db, watchlist_item)
        return {"ok": True, "symbol": symbol}
    except Exception as e:
        logger.warning(f"evaluate-symbol {symbol}: {e}", exc_info=True)
        return {"ok": False, "error": str(e), "symbol": symbol}



