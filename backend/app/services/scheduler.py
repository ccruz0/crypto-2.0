import asyncio
import logging
import time
from datetime import datetime, time as time_module, date
import pytz
from app.services.daily_summary import daily_summary_service
from app.services.telegram_commands import process_telegram_commands
from app.services.sl_tp_checker import sl_tp_checker_service
from app.database import SessionLocal

logger = logging.getLogger(__name__)

# Bali timezone (UTC+8)
BALI_TZ = pytz.timezone('Asia/Makassar')  # Makassar is the same timezone as Bali (WITA)

# Global lock to prevent multiple scheduler instances across all workers
_start_lock = asyncio.Lock()
_start_attempted = False

class TradingScheduler:
    """Scheduler for automated trading tasks"""
    
    def __init__(self):
        self.running = False
        self.daily_summary_time = time_module(8, 0)  # 8:00 AM
        self.sell_orders_report_time = time_module(7, 0)  # 7:00 AM
        self.nightly_consistency_time = time_module(3, 0)  # 3:00 AM
        self.last_sl_tp_check_date = None  # Track last SL/TP check date
        self.last_sell_orders_report_date = None  # Track last sell orders report date
        self.last_nightly_consistency_date = None  # Track last nightly consistency check date
        self._scheduler_task = None  # Track the running task to prevent duplicates
    
    def check_daily_summary_sync(self):
        """Check if it's time to send daily summary - synchronous worker"""
        now = datetime.now().time()
        
        # Check if it's 8:00 AM (with 1 minute tolerance)
        if (self.daily_summary_time.hour == now.hour and 
            abs(self.daily_summary_time.minute - now.minute) <= 1):
            
            logger.info("Sending daily summary...")
            try:
                daily_summary_service.send_daily_summary()
                # Record successful execution
                from app.api.routes_monitoring import record_workflow_execution
                record_workflow_execution("daily_summary", "success", "Daily summary sent successfully")
            except Exception as e:
                logger.error(f"Error sending daily summary: {e}", exc_info=True)
                from app.api.routes_monitoring import record_workflow_execution
                record_workflow_execution("daily_summary", "error", None, str(e))
    
    async def check_daily_summary(self):
        """Check if it's time to send daily summary - async wrapper"""
        now = datetime.now().time()
        
        # Check if it's 8:00 AM (with 1 minute tolerance)
        if (self.daily_summary_time.hour == now.hour and 
            abs(self.daily_summary_time.minute - now.minute) <= 1):
            
            # Run blocking call in thread pool
            await asyncio.to_thread(self.check_daily_summary_sync)
            
            # Wait 2 minutes to avoid duplicate sends
            await asyncio.sleep(120)
    
    def check_sl_tp_positions_sync(self):
        """Check if it's time to check positions for SL/TP - synchronous worker"""
        now = datetime.now()
        today = now.date()
        
        # Check if it's 8:00 AM (with 1 minute tolerance) and we haven't checked today
        if (now.hour == 8 and 
            abs(now.minute) <= 1 and 
            self.last_sl_tp_check_date != today):
            
            logger.info("Checking positions for missing SL/TP orders...")
            
            try:
                db = SessionLocal()
                try:
                    sl_tp_checker_service.send_sl_tp_reminder(db)
                    self.last_sl_tp_check_date = today
                    logger.info("SL/TP check completed")
                    # Record successful execution
                    from app.api.routes_monitoring import record_workflow_execution
                    record_workflow_execution("sl_tp_check", "success", "SL/TP check completed successfully")
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Error checking SL/TP positions: {e}", exc_info=True)
                from app.api.routes_monitoring import record_workflow_execution
                record_workflow_execution("sl_tp_check", "error", None, str(e))
    
    async def check_sl_tp_positions(self):
        """Check if it's time to check positions for SL/TP - async wrapper"""
        now = datetime.now()
        today = now.date()
        
        # Check if it's 8:00 AM (with 1 minute tolerance) and we haven't checked today
        if (now.hour == 8 and 
            abs(now.minute) <= 1 and 
            self.last_sl_tp_check_date != today):
            
            # Run blocking DB/API calls in thread pool
            await asyncio.to_thread(self.check_sl_tp_positions_sync)
            
            # Wait 2 minutes to avoid duplicate checks
            await asyncio.sleep(120)
    
    def check_sell_orders_report_sync(self):
        """Check if it's time to send sell orders report - synchronous worker"""
        # Get current time in Bali timezone
        now_bali = datetime.now(BALI_TZ)
        today_bali = now_bali.date()
        
        # Check if it's 7:00 AM Bali time (with 1 minute tolerance) and we haven't sent today
        if (now_bali.hour == 7 and 
            abs(now_bali.minute) <= 1 and 
            self.last_sell_orders_report_date != today_bali):
            
            logger.info(f"Sending sell orders report... (Bali time: {now_bali.strftime('%Y-%m-%d %H:%M:%S %Z')})")
            
            try:
                db = SessionLocal()
                try:
                    daily_summary_service.send_sell_orders_report(db)
                    self.last_sell_orders_report_date = today_bali
                    logger.info("Sell orders report sent")
                    # Record successful execution
                    from app.api.routes_monitoring import record_workflow_execution
                    record_workflow_execution("sell_orders_report", "success", "Sell orders report sent successfully")
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Error sending sell orders report: {e}", exc_info=True)
                from app.api.routes_monitoring import record_workflow_execution
                record_workflow_execution("sell_orders_report", "error", None, str(e))
    
    async def check_sell_orders_report(self):
        """Check if it's time to send sell orders report - async wrapper"""
        # Get current time in Bali timezone
        now_bali = datetime.now(BALI_TZ)
        today_bali = now_bali.date()
        
        # Check if it's 7:00 AM Bali time (with 1 minute tolerance) and we haven't sent today
        if (now_bali.hour == 7 and 
            abs(now_bali.minute) <= 1 and 
            self.last_sell_orders_report_date != today_bali):
            
            # Run blocking DB/API calls in thread pool
            await asyncio.to_thread(self.check_sell_orders_report_sync)
            
            # Wait 2 minutes to avoid duplicate sends
            await asyncio.sleep(120)
    
    def check_nightly_consistency_sync(self):
        """Check if it's time to run nightly consistency check - synchronous worker"""
        # Get current time in Bali timezone
        now_bali = datetime.now(BALI_TZ)
        today_bali = now_bali.date()
        
        # Check if it's 3:00 AM Bali time (with 1 minute tolerance) and we haven't run today
        if (now_bali.hour == 3 and 
            abs(now_bali.minute) <= 1 and 
            self.last_nightly_consistency_date != today_bali):
            
            logger.info(f"Running nightly consistency check... (Bali time: {now_bali.strftime('%Y-%m-%d %H:%M:%S %Z')})")
            
            try:
                import subprocess
                import sys
                import os
                # Calculate absolute path to the consistency check script
                # In Docker: WORKDIR is /app, backend contents are copied to /app/
                # So structure is: /app/app/services/scheduler.py and /app/scripts/watchlist_consistency_check.py
                # In local dev: .../backend/app/services/scheduler.py and .../backend/scripts/watchlist_consistency_check.py
                current_file_dir = os.path.dirname(os.path.abspath(__file__))
                # current_file_dir is /app/app/services/ in Docker, or .../backend/app/services/ locally
                # Go up 3 levels to get root: /app/ in Docker, or .../backend/ locally
                root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file_dir)))
                # In Docker: root_dir = /app/, scripts are at /app/scripts/
                # In local: root_dir = .../backend/, scripts are at .../backend/scripts/
                # Both Docker and local use the same calculation: root_dir/scripts/ (NOT root_dir/backend/scripts/)
                script_path = os.path.join(root_dir, "scripts", "watchlist_consistency_check.py")
                if not os.path.exists(script_path):
                    raise FileNotFoundError(f"Script not found at {script_path}. Root dir: {root_dir}")
                
                result = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minute timeout
                )
                
                if result.returncode == 0:
                    self.last_nightly_consistency_date = today_bali
                    logger.info("Nightly consistency check completed")
                    # Record successful execution with correct workflow_id
                    from app.api.routes_monitoring import record_workflow_execution
                    record_workflow_execution("watchlist_consistency", "success", "Nightly consistency check completed successfully")
                else:
                    logger.error(f"Nightly consistency check failed with return code {result.returncode}")
                    logger.error(f"STDOUT: {result.stdout}")
                    logger.error(f"STDERR: {result.stderr}")
                    from app.api.routes_monitoring import record_workflow_execution
                    record_workflow_execution("watchlist_consistency", "error", None, f"Return code: {result.returncode}")
            except subprocess.TimeoutExpired:
                logger.error("Nightly consistency check timed out after 10 minutes")
                from app.api.routes_monitoring import record_workflow_execution
                record_workflow_execution("watchlist_consistency", "error", None, "Timeout after 10 minutes")
            except Exception as e:
                logger.error(f"Error running nightly consistency check: {e}", exc_info=True)
                from app.api.routes_monitoring import record_workflow_execution
                record_workflow_execution("watchlist_consistency", "error", None, str(e))
    
    async def check_nightly_consistency(self):
        """Check if it's time to run nightly consistency check - async wrapper"""
        # Get current time in Bali timezone
        now_bali = datetime.now(BALI_TZ)
        today_bali = now_bali.date()
        
        # Check if it's 3:00 AM Bali time (with 1 minute tolerance) and we haven't run today
        if (now_bali.hour == 3 and 
            abs(now_bali.minute) <= 1 and 
            self.last_nightly_consistency_date != today_bali):
            
            # Run blocking script execution in thread pool
            await asyncio.to_thread(self.check_nightly_consistency_sync)
            
            # Wait 2 minutes to avoid duplicate runs
            await asyncio.sleep(120)
    
    def check_telegram_commands_sync(self):
        """Check for pending Telegram commands - synchronous worker"""
        try:
            logger.info("[SCHEDULER] 🔔 Checking Telegram commands...")
            # Get database session
            db = SessionLocal()
            try:
                process_telegram_commands(db)
                # Record execution (only log periodically to avoid spam - every 10th execution)
                if not hasattr(self, '_telegram_commands_count'):
                    self._telegram_commands_count = 0
                self._telegram_commands_count += 1
                if self._telegram_commands_count % 10 == 0:
                    from app.api.routes_monitoring import record_workflow_execution
                    record_workflow_execution("telegram_commands", "success", f"Telegram commands check completed (execution #{self._telegram_commands_count})")
            finally:
                db.close()
            logger.debug("[SCHEDULER] Telegram commands check completed")
        except Exception as e:
            logger.error(f"[TG] Error checking commands: {e}", exc_info=True)
            from app.api.routes_monitoring import record_workflow_execution
            record_workflow_execution("telegram_commands", "error", None, str(e))
    
    async def check_telegram_commands(self):
        """Check for pending Telegram commands - async wrapper"""
        # Run blocking DB/API calls in thread pool
        await asyncio.to_thread(self.check_telegram_commands_sync)
    
    async def update_dashboard_snapshot(self):
        """Update dashboard snapshot cache periodically (every 60 seconds)"""
        try:
            from app.services.dashboard_snapshot import update_dashboard_snapshot
            
            if not hasattr(self, '_last_snapshot_update'):
                self._last_snapshot_update = 0
            
            now = time.time()
            if now - self._last_snapshot_update >= 60:  # Update every 60 seconds
                logger.info("[SCHEDULER] 📸 Updating dashboard snapshot...")
                # update_dashboard_snapshot is now async, so we await it directly
                # Database operations will run in thread pool executor if needed
                result = await update_dashboard_snapshot()
                if result.get("success"):
                    self._last_snapshot_update = time.time()
                    logger.info(f"[SCHEDULER] ✅ Dashboard snapshot updated in {result.get('duration_seconds', 0):.2f}s")
                    # Record successful execution
                    from app.api.routes_monitoring import record_workflow_execution
                    record_workflow_execution("dashboard_snapshot", "success", f"Snapshot updated in {result.get('duration_seconds', 0):.2f}s")
                else:
                    logger.warning(f"[SCHEDULER] ⚠️ Dashboard snapshot update failed: {result.get('error')}")
                    from app.api.routes_monitoring import record_workflow_execution
                    record_workflow_execution("dashboard_snapshot", "error", None, result.get('error', 'Unknown error'))
        except Exception as e:
            logger.error(f"[SCHEDULER] Error updating dashboard snapshot: {e}", exc_info=True)
            from app.api.routes_monitoring import record_workflow_execution
            record_workflow_execution("dashboard_snapshot", "error", None, str(e))
    
    async def run_scheduler(self):
        """Main scheduler loop"""
        logger.info("[SCHEDULER] 🚀 run_scheduler() STARTED")
        
        # Telegram health-check on startup
        try:
            from app.services.telegram_health import check_telegram_health
            check_telegram_health(origin="scheduler_startup")
        except Exception as e:
            logger.warning(f"[SCHEDULER] Failed to run Telegram health-check on startup: {e}")
        
        logger.info("run_scheduler() called - starting scheduler")
        self.running = True
        logger.info("Trading scheduler started - running=True")
        
        logger.info("[SCHEDULER] Entering main scheduler loop")
        loop_count = 0
        while self.running:
            try:
                loop_count += 1
                if loop_count % 10 == 0:  # Log every 10 iterations
                    logger.info(f"[SCHEDULER] Loop iteration #{loop_count}")
                await self.check_daily_summary()
                await self.check_sell_orders_report()
                await self.check_sl_tp_positions()
                await self.check_nightly_consistency()
                # Update dashboard snapshot periodically (every 60 seconds)
                await self.update_dashboard_snapshot()
                # Check Telegram commands continuously (long polling handles timing)
                await self.check_telegram_commands()
                # Short sleep to allow other tasks to run, but check commands immediately again
                # Long polling in get_telegram_updates will wait for new messages
                await asyncio.sleep(1)  # Check every second (long polling waits up to 30s)
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def start(self):
        """Start the scheduler"""
        global _start_attempted
        
        # CRITICAL: Use global lock to prevent multiple scheduler instances across all workers
        async with _start_lock:
            # Check if already attempted globally
            if _start_attempted:
                logger.warning("[SCHEDULER] ⚠️ Scheduler start() already attempted globally, ignoring duplicate call")
                return
            
            # Check if task exists and is still running
            if self._scheduler_task is not None:
                if not self._scheduler_task.done():
                    logger.warning("[SCHEDULER] ⚠️ Scheduler task is already running, ignoring start() call")
                    return
                else:
                    # Task exists but is done - clear it
                    logger.info("[SCHEDULER] Previous scheduler task was done, clearing reference")
                    self._scheduler_task = None
            
            # Also check running flag
            if self.running:
                logger.warning("[SCHEDULER] ⚠️ Scheduler running flag is True but no task found, resetting")
                self.running = False
            
            # Mark as attempted globally
            _start_attempted = True
            
            # Mark as running BEFORE creating task to prevent race conditions
            self.running = True
            
            # Create task to run scheduler in background and track it
            self._scheduler_task = asyncio.create_task(self.run_scheduler())
            logger.info("[SCHEDULER] Scheduler task created and started")
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
        self._scheduler_task = None  # Clear task reference

# Global scheduler instance
trading_scheduler = TradingScheduler()






