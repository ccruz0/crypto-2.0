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
        self.last_sl_tp_check_date = None  # Track last SL/TP check date
        self.last_sell_orders_report_date = None  # Track last sell orders report date
        self._scheduler_task = None  # Track the running task to prevent duplicates
    
    def check_daily_summary_sync(self):
        """Check if it's time to send daily summary - synchronous worker"""
        now = datetime.now().time()
        
        # Check if it's 8:00 AM (with 1 minute tolerance)
        if (self.daily_summary_time.hour == now.hour and 
            abs(self.daily_summary_time.minute - now.minute) <= 1):
            
            logger.info("Sending daily summary...")
            daily_summary_service.send_daily_summary()
    
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
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Error checking SL/TP positions: {e}", exc_info=True)
    
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
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Error sending sell orders report: {e}", exc_info=True)
    
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
    
    def check_telegram_commands_sync(self):
        """Check for pending Telegram commands - synchronous worker"""
        try:
            logger.info("[SCHEDULER] 🔔 Checking Telegram commands...")
            # Get database session
            db = SessionLocal()
            try:
                process_telegram_commands(db)
            finally:
                db.close()
            logger.debug("[SCHEDULER] Telegram commands check completed")
        except Exception as e:
            logger.error(f"[TG] Error checking commands: {e}", exc_info=True)
    
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
                else:
                    logger.warning(f"[SCHEDULER] ⚠️ Dashboard snapshot update failed: {result.get('error')}")
        except Exception as e:
            logger.error(f"[SCHEDULER] Error updating dashboard snapshot: {e}", exc_info=True)
    
    async def run_scheduler(self):
        """Main scheduler loop"""
        logger.info("[SCHEDULER] 🚀 run_scheduler() STARTED")
        
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






