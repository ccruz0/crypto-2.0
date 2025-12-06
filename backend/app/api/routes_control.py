"""Service control API endpoints"""
import asyncio
import logging
import os
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from pydantic import BaseModel

from app.database import get_db
from app.services.exchange_sync import exchange_sync_service
from app.services.signal_monitor import signal_monitor_service
from app.services.scheduler import trading_scheduler
from app.models.trading_settings import TradingSettings
from app.services.telegram_notifier import telegram_notifier

router = APIRouter()
log = logging.getLogger("app.control")


class LiveTradingRequest(BaseModel):
    enabled: bool


def _get_live_trading_from_db(db: Session) -> bool:
    """Get LIVE_TRADING setting from database, fallback to environment variable"""
    try:
        setting = db.query(TradingSettings).filter(
            TradingSettings.setting_key == "LIVE_TRADING"
        ).first()
        
        if setting:
            return setting.setting_value.lower() == "true"
    except Exception as e:
        log.warning(f"Error reading LIVE_TRADING from database: {e}")
    
    # Fallback to environment variable
    return os.getenv("LIVE_TRADING", "false").lower() == "true"


def _set_live_trading_in_db(db: Session, enabled: bool) -> bool:
    """Set LIVE_TRADING setting in database"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Always start with a clean transaction state
            # Rollback any previous failed transaction to avoid "InFailedSqlTransaction" errors
            try:
                db.rollback()
            except:
                pass  # Ignore rollback errors if no transaction exists
            
            # Use a fresh query to avoid any stale state
            setting = db.query(TradingSettings).filter(
                TradingSettings.setting_key == "LIVE_TRADING"
            ).first()
            
            if setting:
                setting.setting_value = "true" if enabled else "false"
                setting.updated_at = func.now()
            else:
                setting = TradingSettings(
                    setting_key="LIVE_TRADING",
                    setting_value="true" if enabled else "false",
                    description="Enable/disable live trading (real orders vs dry run)"
                )
                db.add(setting)
            
            db.commit()
            log.info(f"✅ Successfully set LIVE_TRADING to {enabled} in database (attempt {attempt + 1})")
            return True
        except Exception as e:
            log.error(f"Error setting LIVE_TRADING in database (attempt {attempt + 1}/{max_retries}): {e}", exc_info=True)
            try:
                db.rollback()
            except Exception as rollback_error:
                log.error(f"Error during rollback: {rollback_error}")
            
            # If this was the last attempt, return False
            if attempt == max_retries - 1:
                return False
            
            # Wait a bit before retrying
            import time
            time.sleep(0.1 * (attempt + 1))  # Exponential backoff
    
    return False


@router.post("/services/start")
async def start_services():
    """Start all trading services"""
    try:
        log.info("🚀 Starting all trading services...")
        
        results = {
            "exchange_sync": {"status": "already_running" if exchange_sync_service.is_running else "starting"},
            "signal_monitor": {"status": "already_running" if signal_monitor_service.is_running else "starting"},
            "trading_scheduler": {"status": "already_running" if trading_scheduler.running else "starting"}
        }
        
        # Start Exchange Sync
        if not exchange_sync_service.is_running:
            try:
                asyncio.create_task(exchange_sync_service.start())
                results["exchange_sync"]["status"] = "started"
                log.info("✅ Exchange sync service started")
            except Exception as e:
                results["exchange_sync"]["status"] = "error"
                results["exchange_sync"]["error"] = str(e)
                log.error(f"❌ Failed to start exchange sync: {e}")
        
        # Start Signal Monitor
        if not signal_monitor_service.is_running:
            try:
                asyncio.create_task(signal_monitor_service.start())
                results["signal_monitor"]["status"] = "started"
                log.info("✅ Signal monitor service started")
            except Exception as e:
                results["signal_monitor"]["status"] = "error"
                results["signal_monitor"]["error"] = str(e)
                log.error(f"❌ Failed to start signal monitor: {e}")
        
        # Start Trading Scheduler
        if not trading_scheduler.running:
            try:
                # Use start() method which has protection against duplicates
                await trading_scheduler.start()
                results["trading_scheduler"]["status"] = "started"
                log.info("✅ Trading scheduler started")
            except Exception as e:
                results["trading_scheduler"]["status"] = "error"
                results["trading_scheduler"]["error"] = str(e)
                log.error(f"❌ Failed to start trading scheduler: {e}")
        
        # Wait a bit for services to initialize
        await asyncio.sleep(2)
        
        # Check status after starting
        final_status = {
            "exchange_sync_running": exchange_sync_service.is_running,
            "signal_monitor_running": signal_monitor_service.is_running,
            "trading_scheduler_running": trading_scheduler.running,
            "results": results
        }
        
        log.info(f"📊 Services status: {final_status}")
        
        return final_status
        
    except Exception as e:
        log.error(f"Error starting services: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/services/status")
def get_services_status():
    """Get status of all trading services"""
    return {
        "exchange_sync_running": exchange_sync_service.is_running,
        "signal_monitor_running": signal_monitor_service.is_running,
        "trading_scheduler_running": trading_scheduler.running,
        "last_sync": exchange_sync_service.last_sync.isoformat() if exchange_sync_service.last_sync else None
    }


@router.post("/services/stop")
def stop_services():
    """Stop all trading services"""
    try:
        log.info("🛑 Stopping all trading services...")
        
        exchange_sync_service.stop()
        signal_monitor_service.stop()
        trading_scheduler.stop()
        
        log.info("✅ All services stopped")
        
        return {
            "ok": True,
            "message": "All services stopped",
            "status": {
                "exchange_sync_running": exchange_sync_service.is_running,
                "signal_monitor_running": signal_monitor_service.is_running,
                "trading_scheduler_running": trading_scheduler.running
            }
        }
    except Exception as e:
        log.error(f"Error stopping services: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trading/live-status")
def get_live_trading_status(db: Session = Depends(get_db)):
    """Get current LIVE_TRADING status"""
    try:
        enabled = _get_live_trading_from_db(db)
        
        # Also check environment variable as fallback
        env_enabled = os.getenv("LIVE_TRADING", "false").lower() == "true"
        
        response = {
            "ok": True,
            "success": True,
            "live_trading_enabled": enabled,
            "env_live_trading": env_enabled,
            "mode": "LIVE" if enabled else "DRY_RUN",
            "message": "Live trading is ENABLED - Real orders will be placed" if enabled else "Live trading is DISABLED - Orders are simulated (DRY RUN)"
        }
        log.info(f"📣 live-status response: {response}")
        return response
    except Exception as e:
        log.error(f"Error getting live trading status: {e}", exc_info=True)
        return {"ok": False, "success": False, "error": str(e), "mode": "DRY_RUN"}


@router.post("/trading/live-toggle")
def toggle_live_trading(
    request: LiveTradingRequest,
    db: Session = Depends(get_db)
):
    """Toggle LIVE_TRADING on/off for all coins"""
    try:
        enabled = request.enabled
        
        # Save to database
        success = _set_live_trading_in_db(db, enabled)
        
        if not success:
            log.error("Failed to save LIVE_TRADING setting to database")
            return {"ok": False, "success": False, "error": "Failed to save LIVE_TRADING setting to database"}
        
        # Also update environment variable (for current session)
        os.environ["LIVE_TRADING"] = "true" if enabled else "false"
        
        mode = "LIVE" if enabled else "DRY_RUN"
        log.warning(f"⚠️ LIVE_TRADING toggled to {mode} - {'REAL orders will be placed' if enabled else 'Orders are simulated'}")
        
        response = {
            "ok": True,
            "success": True,
            "live_trading_enabled": enabled,
            "mode": mode,
            "message": f"Live trading {'ENABLED' if enabled else 'DISABLED'} - {'Real orders will be placed' if enabled else 'Orders are simulated (DRY RUN)'}"
        }
        log.info(f"📣 live-toggle response: {response}")
        return response
    except Exception as e:
        log.error(f"Error toggling live trading: {e}", exc_info=True)
        # Always return JSON on error
        return {"ok": False, "success": False, "error": str(e), "mode": "DRY_RUN"}


@router.post("/telegram/update-commands")
def update_telegram_commands():
    """Update Telegram bot commands to only show /menu"""
    try:
        success = telegram_notifier.set_bot_commands()
        if success:
            return {
                "ok": True,
                "message": "Telegram bot commands updated successfully. Only /menu will be shown."
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update Telegram bot commands")
    except Exception as e:
        log.error(f"Error updating Telegram commands: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

