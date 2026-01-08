import asyncio
import logging
import time
from datetime import datetime, time as time_module, date, timezone
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
        self.last_daily_summary_date = None  # Track last daily summary date
        self.last_sl_tp_check_date = None  # Track last SL/TP check date
        self.last_sell_orders_report_date = None  # Track last sell orders report date
        self.last_nightly_consistency_date = None  # Track last nightly consistency check date
        self.last_hourly_sl_tp_check = None  # Track last hourly SL/TP check (datetime)
        self._scheduler_task = None  # Track the running task to prevent duplicates
        # Locks for atomic check-and-set operations on date tracking variables
        self._daily_summary_lock = asyncio.Lock()
        self._sl_tp_check_lock = asyncio.Lock()
        self._sell_orders_report_lock = asyncio.Lock()
        self._nightly_consistency_lock = asyncio.Lock()
        self._hourly_sl_tp_check_lock = asyncio.Lock()
    
    def check_daily_summary_sync(self):
        """Check if it's time to send daily summary - synchronous worker
        Note: Date check is performed in async wrapper to ensure atomicity.
        This function is called only after the date has been set in the async wrapper.
        """
        logger.info("Sending daily summary...")
        try:
            daily_summary_service.send_daily_summary()
            logger.info("Daily summary sent")
            # Record successful execution (no report file for daily summary)
            from app.api.routes_monitoring import record_workflow_execution
            record_workflow_execution("daily_summary", "success", None)
        except Exception as e:
            logger.error(f"Error sending daily summary: {e}", exc_info=True)
            from app.api.routes_monitoring import record_workflow_execution
            record_workflow_execution("daily_summary", "error", None, str(e))
    
    async def check_daily_summary(self):
        """Check if it's time to send daily summary - async wrapper"""
        now = datetime.now()
        today = now.date()
        now_time = now.time()
        
        # Use lock to make check-and-set atomic, preventing concurrent execution
        async with self._daily_summary_lock:
            # Check if it's 8:00 AM (with 1 minute tolerance) and we haven't sent today
            if (self.daily_summary_time.hour == now_time.hour and 
                abs(self.daily_summary_time.minute - now_time.minute) <= 1 and
                self.last_daily_summary_date != today):
                
                # Set date immediately to prevent concurrent requests from passing the check
                self.last_daily_summary_date = today
                
                # Run blocking call in thread pool
                await asyncio.to_thread(self.check_daily_summary_sync)
                
                # Wait 2 minutes to avoid duplicate sends
                await asyncio.sleep(120)
    
    def check_sl_tp_positions_sync(self):
        """Check if it's time to check positions for SL/TP - synchronous worker
        Note: Date check is performed in async wrapper to ensure atomicity.
        This function is called only after the date has been set in the async wrapper.
        """
        logger.info("Checking positions for missing SL/TP orders...")
        
        try:
            db = SessionLocal()
            try:
                sl_tp_checker_service.send_sl_tp_reminder(db)
                logger.info("SL/TP check completed")
                # Record successful execution (no report file for SL/TP check)
                from app.api.routes_monitoring import record_workflow_execution
                record_workflow_execution("sl_tp_check", "success", None)
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
        
        # Use lock to make check-and-set atomic, preventing concurrent execution
        async with self._sl_tp_check_lock:
            # Check if it's 8:00 AM (with 1 minute tolerance) and we haven't checked today
            if (now.hour == 8 and 
                abs(now.minute) <= 1 and 
                self.last_sl_tp_check_date != today):
                
                # Set date immediately to prevent concurrent requests from passing the check
                self.last_sl_tp_check_date = today
                
                # Run blocking DB/API calls in thread pool
                await asyncio.to_thread(self.check_sl_tp_positions_sync)
                
                # Wait 2 minutes to avoid duplicate checks
                await asyncio.sleep(120)
    
    def check_sell_orders_report_sync(self):
        """Check if it's time to send sell orders report - synchronous worker
        Note: Date check is performed in async wrapper to ensure atomicity.
        This function is called only after the date has been set in the async wrapper.
        """
        now_bali = datetime.now(BALI_TZ)
        logger.info(f"Sending sell orders report... (Bali time: {now_bali.strftime('%Y-%m-%d %H:%M:%S %Z')})")
        
        try:
            db = SessionLocal()
            try:
                daily_summary_service.send_sell_orders_report(db)
                logger.info("Sell orders report sent")
                # Record successful execution (no report file for sell orders report)
                from app.api.routes_monitoring import record_workflow_execution
                record_workflow_execution("sell_orders_report", "success", None)
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
        
        # Use lock to make check-and-set atomic, preventing concurrent execution
        async with self._sell_orders_report_lock:
            # Check if it's 7:00 AM Bali time (with 1 minute tolerance) and we haven't sent today
            if (now_bali.hour == 7 and 
                abs(now_bali.minute) <= 1 and 
                self.last_sell_orders_report_date != today_bali):
                
                # Set date immediately to prevent concurrent requests from passing the check
                self.last_sell_orders_report_date = today_bali
                
                # Run blocking DB/API calls in thread pool
                await asyncio.to_thread(self.check_sell_orders_report_sync)
                
                # Wait 2 minutes to avoid duplicate sends
                await asyncio.sleep(120)
    
    def check_nightly_consistency_sync(self):
        """Check if it's time to run nightly consistency check - synchronous worker
        Note: Date check is performed in async wrapper to ensure atomicity.
        This function is called only after the date has been set in the async wrapper.
        """
        now_bali = datetime.now(BALI_TZ)
        logger.info(f"Running nightly consistency check... (Bali time: {now_bali.strftime('%Y-%m-%d %H:%M:%S %Z')})")
        
        try:
            import subprocess
            import sys
            import os
            # Calculate absolute path to the consistency check script
            # In Docker: WORKDIR is /app, backend contents are copied to /app/
            # So structure is: /app/services/scheduler.py and /app/scripts/watchlist_consistency_check.py
            # In local dev: .../backend/app/services/scheduler.py and .../backend/scripts/watchlist_consistency_check.py
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            # current_file_dir is /app/services/ in Docker, or .../backend/app/services/ locally
            # Go up 2 levels to get backend root: /app/ in Docker, or .../backend/ locally
            backend_root = os.path.dirname(os.path.dirname(current_file_dir))
            # In Docker: backend_root = /app/, scripts are at /app/scripts/
            # In local: backend_root = .../backend/, scripts are at .../backend/scripts/
            script_path = os.path.join(backend_root, "scripts", "watchlist_consistency_check.py")
            if not os.path.exists(script_path):
                raise FileNotFoundError(f"Script not found at {script_path}. Backend root: {backend_root}")
            
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )
            
            # Date is already set in async wrapper to prevent concurrent execution
            if result.returncode == 0:
                logger.info("Nightly consistency check completed")
                # Record successful execution with correct workflow_id and report path
                from app.api.routes_monitoring import record_workflow_execution
                from datetime import datetime
                import os
                date_str = datetime.now().strftime("%Y%m%d")
                # Report is generated in docs/monitoring/ relative to project root
                project_root = os.path.dirname(backend_root)
                report_path = os.path.join("docs", "monitoring", f"watchlist_consistency_report_latest.md")
                # Also check if dated report exists
                dated_report = os.path.join("docs", "monitoring", f"watchlist_consistency_report_{date_str}.md")
                if os.path.exists(os.path.join(project_root, dated_report)):
                    report_path = dated_report
                record_workflow_execution("watchlist_consistency", "success", report_path)
            else:
                logger.error(f"Nightly consistency check failed with return code {result.returncode}")
                logger.error(f"STDOUT: {result.stdout}")
                logger.error(f"STDERR: {result.stderr}")
                from app.api.routes_monitoring import record_workflow_execution
                record_workflow_execution("watchlist_consistency", "error", None, f"Return code: {result.returncode}")
        except subprocess.TimeoutExpired:
            # Date is already set in async wrapper to prevent retries
            logger.error("Nightly consistency check timed out after 10 minutes")
            from app.api.routes_monitoring import record_workflow_execution
            record_workflow_execution("watchlist_consistency", "error", None, "Timeout after 10 minutes")
        except Exception as e:
            # Date is already set in async wrapper to prevent retries
            logger.error(f"Error running nightly consistency check: {e}", exc_info=True)
            from app.api.routes_monitoring import record_workflow_execution
            record_workflow_execution("watchlist_consistency", "error", None, str(e))
    
    async def check_nightly_consistency(self):
        """Check if it's time to run nightly consistency check - async wrapper"""
        # Get current time in Bali timezone
        now_bali = datetime.now(BALI_TZ)
        today_bali = now_bali.date()
        now_bali_time = now_bali.time()
        
        # Use lock to make check-and-set atomic, preventing concurrent execution
        async with self._nightly_consistency_lock:
            # Check if it's time to run (with 1 minute tolerance) and we haven't run today
            # Use self.nightly_consistency_time to respect configuration changes
            if (self.nightly_consistency_time.hour == now_bali_time.hour and 
                abs(self.nightly_consistency_time.minute - now_bali_time.minute) <= 1 and 
                self.last_nightly_consistency_date != today_bali):
                
                # Set date immediately to prevent concurrent requests from passing the check
                self.last_nightly_consistency_date = today_bali
                
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
                    # Record periodic status (no report file for telegram commands)
                    record_workflow_execution("telegram_commands", "success", None)
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
    
    def check_hourly_sl_tp_missed_sync(self):
        """Check for FILLED orders missing SL/TP - synchronous worker
        Runs hourly to catch orders that were missed by the 1-hour automatic window
        """
        logger.info("Checking for FILLED orders missing SL/TP (hourly check)...")
        
        try:
            from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
            from app.services.exchange_sync import ExchangeSyncService
            from app.services.telegram_notifier import telegram_notifier
            from datetime import timedelta, timezone
            
            db = SessionLocal()
            try:
                exchange_sync = ExchangeSyncService()
                now_utc = datetime.now(timezone.utc)
                
                # Check orders filled in last 3 hours
                three_hours_ago = now_utc - timedelta(hours=3)
                
                # Find FILLED orders from last 3 hours that don't have SL/TP
                filled_orders = db.query(ExchangeOrder).filter(
                    ExchangeOrder.status == OrderStatusEnum.FILLED,
                    ExchangeOrder.exchange_update_time >= three_hours_ago,
                    # Exclude SL/TP orders themselves
                    ~ExchangeOrder.order_type.in_(['STOP_LIMIT', 'STOP_LOSS_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT_LIMIT', 'TAKE_PROFIT'])
                ).all()
                
                orders_missing_sl_tp = []
                orders_too_old = []
                orders_created = 0
                
                for order in filled_orders:
                    # Check if SL/TP exist
                    sl_count = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == order.exchange_order_id,
                        ExchangeOrder.order_role == 'STOP_LOSS'
                    ).count()
                    
                    tp_count = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == order.exchange_order_id,
                        ExchangeOrder.order_role == 'TAKE_PROFIT'
                    ).count()
                    
                    if sl_count == 0 or tp_count == 0:
                        # Calculate time since filled
                        filled_time = order.exchange_update_time or order.exchange_create_time
                        if filled_time:
                            if filled_time.tzinfo is None:
                                filled_time = filled_time.replace(tzinfo=timezone.utc)
                            time_since_filled = (now_utc - filled_time).total_seconds() / 3600  # hours
                            
                            order_info = {
                                'order_id': order.exchange_order_id,
                                'symbol': order.symbol,
                                'side': order.side.value,
                                'price': float(order.avg_price) if order.avg_price else (float(order.price) if order.price else 0),
                                'quantity': float(order.quantity) if order.quantity else 0,
                                'filled_time': filled_time,
                                'time_since_filled': time_since_filled,
                                'has_sl': sl_count > 0,
                                'has_tp': tp_count > 0
                            }
                            
                            # Try to create SL/TP if <3 hours old
                            if time_since_filled < 3.0:
                                try:
                                    filled_price = float(order.avg_price) if order.avg_price else (float(order.price) if order.price else 0)
                                    filled_qty = float(order.cumulative_quantity) if order.cumulative_quantity else (float(order.quantity) if order.quantity else 0)
                                    
                                    if filled_price > 0 and filled_qty > 0:
                                        logger.info(f"🔄 Attempting to create SL/TP for missed order {order.exchange_order_id} ({order.symbol}) - filled {time_since_filled:.2f} hours ago")
                                        exchange_sync._create_sl_tp_for_filled_order(
                                            db=db,
                                            symbol=order.symbol,
                                            side=order.side.value,
                                            filled_price=filled_price,
                                            filled_qty=filled_qty,
                                            order_id=order.exchange_order_id,
                                            force=True,
                                            source="hourly_check"
                                        )
                                        
                                        # Verify creation
                                        db.refresh(order)
                                        sl_new = db.query(ExchangeOrder).filter(
                                            ExchangeOrder.parent_order_id == order.exchange_order_id,
                                            ExchangeOrder.order_role == 'STOP_LOSS'
                                        ).count()
                                        tp_new = db.query(ExchangeOrder).filter(
                                            ExchangeOrder.parent_order_id == order.exchange_order_id,
                                            ExchangeOrder.order_role == 'TAKE_PROFIT'
                                        ).count()
                                        
                                        if sl_new > 0 and tp_new > 0:
                                            orders_created += 1
                                            logger.info(f"✅ Successfully created SL/TP for order {order.exchange_order_id}")
                                        else:
                                            orders_missing_sl_tp.append(order_info)
                                    else:
                                        orders_missing_sl_tp.append(order_info)
                                except Exception as e:
                                    logger.error(f"❌ Failed to create SL/TP for order {order.exchange_order_id}: {e}", exc_info=True)
                                    orders_missing_sl_tp.append(order_info)
                            else:
                                # Order is >3 hours old - too late to auto-create
                                orders_too_old.append(order_info)
                
                # Send Telegram notification if there are issues
                if orders_too_old or (orders_missing_sl_tp and orders_created == 0):
                    try:
                        message_parts = ["🔍 <b>HOURLY SL/TP CHECK</b>\n\n"]
                        
                        if orders_created > 0:
                            message_parts.append(f"✅ Created SL/TP for {orders_created} missed order(s)\n\n")
                        
                        if orders_too_old:
                            message_parts.append(f"⚠️ <b>{len(orders_too_old)} order(s) too old for auto-creation (>3 hours):</b>\n")
                            for o in orders_too_old[:5]:  # Limit to 5 for brevity
                                message_parts.append(
                                    f"• {o['symbol']} {o['side']} - {o['order_id']}\n"
                                    f"  Filled {o['time_since_filled']:.1f}h ago | Missing: {'SL' if not o['has_sl'] else ''} {'TP' if not o['has_tp'] else ''}\n"
                                )
                            if len(orders_too_old) > 5:
                                message_parts.append(f"  ... and {len(orders_too_old) - 5} more\n")
                            message_parts.append("\n💡 Manual intervention required\n")
                        
                        if orders_missing_sl_tp and orders_created == 0:
                            message_parts.append(f"❌ <b>{len(orders_missing_sl_tp)} order(s) failed SL/TP creation:</b>\n")
                            for o in orders_missing_sl_tp[:3]:
                                message_parts.append(f"• {o['symbol']} {o['side']} - {o['order_id']}\n")
                            if len(orders_missing_sl_tp) > 3:
                                message_parts.append(f"  ... and {len(orders_missing_sl_tp) - 3} more\n")
                        
                        if len(message_parts) > 1:  # Only send if there's content beyond header
                            telegram_notifier.send_message("".join(message_parts))
                            logger.info(f"Sent hourly SL/TP check notification")
                    except Exception as notify_err:
                        logger.warning(f"Failed to send hourly SL/TP check notification: {notify_err}", exc_info=True)
                
                if orders_created == 0 and not orders_too_old and not orders_missing_sl_tp:
                    logger.info("✅ All recent FILLED orders have SL/TP protection")
                
                # Record execution
                from app.api.routes_monitoring import record_workflow_execution
                record_workflow_execution("hourly_sl_tp_check", "success", None)
                
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in hourly SL/TP check: {e}", exc_info=True)
            from app.api.routes_monitoring import record_workflow_execution
            record_workflow_execution("hourly_sl_tp_check", "error", None, str(e))
    
    async def check_hourly_sl_tp_missed(self):
        """Check for FILLED orders missing SL/TP - async wrapper
        Runs every hour at :00 minutes
        """
        now = datetime.now(timezone.utc)
        
        # Check if it's a new hour (minute is 0-1, and we haven't checked this hour)
        should_check = (
            now.minute <= 1 and
            (self.last_hourly_sl_tp_check is None or
             self.last_hourly_sl_tp_check.hour != now.hour or
             self.last_hourly_sl_tp_check.date() != now.date())
        )
        
        async with self._hourly_sl_tp_check_lock:
            if should_check:
                # Set timestamp immediately to prevent concurrent execution
                self.last_hourly_sl_tp_check = now
                
                # Run blocking DB/API calls in thread pool
                await asyncio.to_thread(self.check_hourly_sl_tp_missed_sync)
                
                # Wait 2 minutes to avoid duplicate checks
                await asyncio.sleep(120)
    
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
                    # Record successful execution (no report file for snapshot workflow)
                    from app.api.routes_monitoring import record_workflow_execution
                    record_workflow_execution("dashboard_snapshot", "success", None)
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
                # DISABLED: Hourly SL/TP check - use Telegram menu button instead
                # await self.check_hourly_sl_tp_missed()  # Check for missed SL/TP every hour
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






