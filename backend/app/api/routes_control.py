"""Service control API endpoints"""
import asyncio
import logging
import os
from fastapi import APIRouter, HTTPException, Depends
from starlette.requests import Request
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


class TelegramSettingsRequest(BaseModel):
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


def _get_telegram_enabled_from_db(db: Session, env: str) -> bool:
    """
    Get Telegram enabled setting from database for specific environment.
    
    Defaults:
    - tg_enabled_local = true (local can send)
    - tg_enabled_aws = false (AWS blocked by default for safety)
    """
    try:
        setting_key = f"tg_enabled_{env.lower()}"
        setting = db.query(TradingSettings).filter(
            TradingSettings.setting_key == setting_key
        ).first()
        
        if setting:
            return setting.setting_value.lower() == "true"
    except Exception as e:
        log.warning(f"Error reading {setting_key} from database: {e}")
    
    # Defaults: true for local, false for AWS (safe defaults)
    return env == "local"


def _set_telegram_enabled_in_db(db: Session, env: str, enabled: bool) -> bool:
    """Set Telegram enabled setting in database for specific environment"""
    max_retries = 3
    setting_key = f"tg_enabled_{env.lower()}"
    
    for attempt in range(max_retries):
        try:
            # Always start with a clean transaction state
            try:
                db.rollback()
            except:
                pass  # Ignore rollback errors if no transaction exists
            
            # Use a fresh query to avoid any stale state
            setting = db.query(TradingSettings).filter(
                TradingSettings.setting_key == setting_key
            ).first()
            
            if setting:
                setting.setting_value = "true" if enabled else "false"
                setting.updated_at = func.now()
            else:
                setting = TradingSettings(
                    setting_key=setting_key,
                    setting_value="true" if enabled else "false",
                    description=f"Enable/disable Telegram alerts for {env.upper()} environment"
                )
                db.add(setting)
            
            db.commit()
            log.info(f"✅ Successfully set {setting_key} to {enabled} in database (attempt {attempt + 1})")
            return True
        except Exception as e:
            log.error(f"Error setting {setting_key} in database (attempt {attempt + 1}/{max_retries}): {e}", exc_info=True)
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


@router.get("/settings/telegram")
def get_telegram_settings(db: Session = Depends(get_db)):
    """
    Get Telegram kill switch status for current environment (STEP 4).
    
    Returns:
        {
            "env": "local" | "aws",
            "enabled": bool
        }
    - Reads ONLY the env-specific key (tg_enabled_local or tg_enabled_aws)
    - Never allows cross-env reads
    """
    try:
        from app.core.environment import getRuntimeEnv
        
        # Use getRuntimeEnv() for authoritative environment detection
        environment = getRuntimeEnv()  # Returns "local" or "aws"
        
        # Get enabled status for current environment ONLY
        enabled = _get_telegram_enabled_from_db(db, environment)
        
        # Also get status for the other environment (for display only, read-only)
        other_env = "aws" if environment == "local" else "local"
        other_enabled = _get_telegram_enabled_from_db(db, other_env)
        
        # Determine effective send status (same logic as guard)
        from app.services.telegram_notifier import _get_telegram_kill_switch_status
        settings = Settings()
        
        # Check credentials
        if environment == "aws":
            has_token = bool((os.getenv("TELEGRAM_BOT_TOKEN_AWS") or settings.TELEGRAM_BOT_TOKEN_AWS or "").strip())
            has_chat_id = bool((os.getenv("TELEGRAM_CHAT_ID_AWS") or settings.TELEGRAM_CHAT_ID_AWS or "").strip())
            has_local_creds = bool((os.getenv("TELEGRAM_BOT_TOKEN_LOCAL") or settings.TELEGRAM_BOT_TOKEN_LOCAL or "").strip()) or \
                            bool((os.getenv("TELEGRAM_CHAT_ID_LOCAL") or settings.TELEGRAM_CHAT_ID_LOCAL or "").strip())
        else:  # local
            has_token = bool((os.getenv("TELEGRAM_BOT_TOKEN_LOCAL") or settings.TELEGRAM_BOT_TOKEN_LOCAL or "").strip()) or \
                      bool((os.getenv("TELEGRAM_BOT_TOKEN") or settings.TELEGRAM_BOT_TOKEN or "").strip())
            has_chat_id = bool((os.getenv("TELEGRAM_CHAT_ID_LOCAL") or settings.TELEGRAM_CHAT_ID_LOCAL or "").strip()) or \
                         bool((os.getenv("TELEGRAM_CHAT_ID") or settings.TELEGRAM_CHAT_ID or "").strip())
            has_local_creds = False
        
        # Determine effective status (same logic as send_message guard)
        effective_allowed = enabled and has_token and has_chat_id
        if environment == "aws" and has_local_creds:
            effective_allowed = False
        
        effective_reason = None
        if not enabled:
            effective_reason = "kill_switch_disabled"
        elif not has_token or not has_chat_id:
            effective_reason = f"missing_{environment}_credentials"
        elif environment == "aws" and has_local_creds:
            effective_reason = "aws_has_local_credentials"
        
        # Return normalized effective_status string
        effective_status = "allowed" if effective_allowed else "blocked"
        
        return {
            "env": environment,
            "enabled": enabled,
            "other_env": {
                "env": other_env,
                "enabled": other_enabled
            },
            "credentials_present": has_token and has_chat_id,
            "effective_status": effective_status,
            "blocked_reason": effective_reason if not effective_allowed else None
        }
    except Exception as e:
        log.error(f"Error getting Telegram settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings/telegram")
def update_telegram_settings(
    request: TelegramSettingsRequest,
    db: Session = Depends(get_db)
):
    """
    Update Telegram kill switch for current environment only (STEP 4).
    
    Body: { "enabled": bool }
    - Updates ONLY the env-specific key (tg_enabled_local or tg_enabled_aws)
    - Never allows cross-env writes
    """
    try:
        from app.core.environment import getRuntimeEnv
        
        # Use getRuntimeEnv() for authoritative environment detection
        environment = getRuntimeEnv()  # Returns "local" or "aws"
        
        # Update ONLY the current environment's setting
        success = _set_telegram_enabled_in_db(db, environment, request.enabled)
        
        if not success:
            log.error(f"Failed to save tg_enabled_{environment} setting to database")
            raise HTTPException(status_code=500, detail=f"Failed to save Telegram setting for {environment}")
        
        log.warning(f"⚠️ Telegram kill switch for {environment.upper()} toggled to {request.enabled}")
        
        return {
            "ok": True,
            "env": environment,
            "enabled": request.enabled,
            "message": f"Telegram alerts for {environment.upper()} {'ENABLED' if request.enabled else 'DISABLED'}"
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating Telegram settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/control/telegram/test")
def test_telegram_message(request: Request, db: Session = Depends(get_db)):
    """
    Send a test Telegram message (guarded by kill switch and credentials).
    
    This endpoint respects the same guard as production sends:
    - Checks kill switch status
    - Verifies credentials are present
    - Blocks if AWS tries to use LOCAL credentials
    
    Security:
    - Only enabled when ENABLE_TG_TEST_ENDPOINT=true OR request is from localhost
    - Response indicates if message was blocked and why
    - Never returns secrets in response
    """
    import socket
    from datetime import datetime
    from app.core.environment import getRuntimeEnv
    
    # Security check: Only allow if explicitly enabled OR localhost
    enable_test = os.getenv("ENABLE_TG_TEST_ENDPOINT", "false").lower() == "true"
    is_localhost = False
    try:
        # Check if request is from localhost
        if request.client:
            client_host = getattr(request.client, "host", None)
            is_localhost = client_host in ("127.0.0.1", "localhost", "::1")
        else:
            # If no client info, assume localhost (dev environment)
            is_localhost = True
    except:
        pass
    
    if not enable_test and not is_localhost:
        raise HTTPException(
            status_code=403,
            detail="Test endpoint disabled. Set ENABLE_TG_TEST_ENDPOINT=true to enable."
        )
    
    try:
        runtime_env = getRuntimeEnv()
        timestamp = datetime.now().isoformat()
        test_message = f"TEST TG {timestamp}"
        
        # Attempt to send via telegram_notifier (respects guard)
        result = telegram_notifier.send_message(test_message, origin=runtime_env.upper())
        
        if result:
            return {
                "ok": True,
                "blocked": False,
                "message": "Test message sent successfully",
                "env": runtime_env
            }
        else:
            # Message was blocked by guard
            # Determine reason from guard logic
            from app.services.telegram_notifier import _get_telegram_kill_switch_status
            kill_switch_enabled = _get_telegram_kill_switch_status(runtime_env)
            
            reason = "unknown"
            if not kill_switch_enabled:
                reason = "kill_switch_disabled"
            elif runtime_env == "aws":
                has_aws_token = bool(os.getenv("TELEGRAM_BOT_TOKEN_AWS", "").strip())
                has_aws_chat_id = bool(os.getenv("TELEGRAM_CHAT_ID_AWS", "").strip())
                if not has_aws_token or not has_aws_chat_id:
                    reason = "missing_aws_credentials"
            else:  # local
                has_local_token = bool(os.getenv("TELEGRAM_BOT_TOKEN_LOCAL") or os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
                has_local_chat_id = bool(os.getenv("TELEGRAM_CHAT_ID_LOCAL") or os.getenv("TELEGRAM_CHAT_ID", "").strip())
                if not has_local_token or not has_local_chat_id:
                    reason = "missing_local_credentials"
            
            return {
                "ok": False,
                "blocked": True,
                "reason": reason,
                "message": f"Test message blocked: {reason}",
                "env": runtime_env
            }
    except Exception as e:
        log.error(f"Error in test Telegram endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/health/fix")
async def fix_backend_health():
    """Fix backend health issues by restarting services and clearing errors"""
    try:
        log.info("🔧 Fixing backend health - restarting services...")
        
        # Stop all services first
        try:
            exchange_sync_service.stop()
            signal_monitor_service.stop()
            trading_scheduler.stop()
            log.info("✅ Services stopped")
        except Exception as e:
            log.warning(f"Error stopping services (may already be stopped): {e}")
        
        # Wait a moment for clean shutdown
        await asyncio.sleep(1)
        
        # Restart all services
        results = {
            "exchange_sync": {"status": "restarting"},
            "signal_monitor": {"status": "restarting"},
            "trading_scheduler": {"status": "restarting"}
        }
        
        # Start Exchange Sync
        try:
            asyncio.create_task(exchange_sync_service.start())
            results["exchange_sync"]["status"] = "restarted"
            log.info("✅ Exchange sync service restarted")
        except Exception as e:
            results["exchange_sync"]["status"] = "error"
            results["exchange_sync"]["error"] = str(e)
            log.error(f"❌ Failed to restart exchange sync: {e}")
        
        # Start Signal Monitor
        try:
            asyncio.create_task(signal_monitor_service.start())
            results["signal_monitor"]["status"] = "restarted"
            log.info("✅ Signal monitor service restarted")
        except Exception as e:
            results["signal_monitor"]["status"] = "error"
            results["signal_monitor"]["error"] = str(e)
            log.error(f"❌ Failed to restart signal monitor: {e}")
        
        # Start Trading Scheduler
        try:
            await trading_scheduler.start()
            results["trading_scheduler"]["status"] = "restarted"
            log.info("✅ Trading scheduler restarted")
        except Exception as e:
            results["trading_scheduler"]["status"] = "error"
            results["trading_scheduler"]["error"] = str(e)
            log.error(f"❌ Failed to restart trading scheduler: {e}")
        
        # Wait for services to initialize
        await asyncio.sleep(2)
        
        # Check final status
        final_status = {
            "ok": True,
            "message": "Backend health fix attempted - services restarted",
            "exchange_sync_running": exchange_sync_service.is_running,
            "signal_monitor_running": signal_monitor_service.is_running,
            "trading_scheduler_running": trading_scheduler.running,
            "results": results
        }
        
        log.info(f"📊 Health fix completed: {final_status}")
        
        return final_status
        
    except Exception as e:
        log.error(f"Error fixing backend health: {e}", exc_info=True)
        return {
            "ok": False,
            "error": str(e),
            "message": "Failed to fix backend health"
        }

