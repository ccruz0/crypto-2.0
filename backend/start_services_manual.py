#!/usr/bin/env python3
"""
DEBUG ONLY – DO NOT RUN IN PRODUCTION

Manual service starter - to be run inside the container for debugging only.

⚠️ WARNING: Do NOT run this in production because:
- All services (scheduler, SignalMonitorService, exchange_sync) are already started
  by the main FastAPI app (backend/app/main.py)
- Running this would create duplicate service instances
- This would cause duplicate alerts, duplicate orders, and data inconsistencies
- In production, only the AWS backend container should run these services

Use this script ONLY for:
- Local debugging when the main app is not running
- Testing services in isolation
- Development scenarios where you need to debug services separately

For production, all services are automatically started by the FastAPI app.
"""
import asyncio
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start_services():
    """Start all trading services"""
    logger.info("=" * 60)
    logger.info("🚀 STARTING TRADING SERVICES MANUALLY")
    logger.info("=" * 60)
    
    # 1. Trading Scheduler
    try:
        logger.info("🔧 Starting Trading Scheduler...")
        from app.services.scheduler import trading_scheduler
        asyncio.create_task(trading_scheduler.run_scheduler())
        logger.info("✅ Trading Scheduler started")
    except Exception as e:
        logger.error(f"❌ Failed to start Trading Scheduler: {e}", exc_info=True)
    
    # 2. Exchange Sync Service
    try:
        logger.info("🔧 Starting Exchange Sync Service...")
        from app.services.exchange_sync import exchange_sync_service
        asyncio.create_task(exchange_sync_service.start())
        logger.info("✅ Exchange Sync Service started")
    except Exception as e:
        logger.error(f"❌ Failed to start Exchange Sync Service: {e}", exc_info=True)
    
    # 3. Signal Monitor Service
    try:
        logger.info("🔧 Starting Signal Monitor Service...")
        from app.services.signal_monitor import signal_monitor_service
        asyncio.create_task(signal_monitor_service.start())
        logger.info("✅ Signal Monitor Service started")
    except Exception as e:
        logger.error(f"❌ Failed to start Signal Monitor Service: {e}", exc_info=True)
    
    logger.info("=" * 60)
    logger.info("✅ ALL SERVICES STARTED - Keeping alive...")
    logger.info("=" * 60)
    
    # Keep the script running
    while True:
        await asyncio.sleep(60)
        logger.info("💓 Services are running...")

if __name__ == "__main__":
    try:
        asyncio.run(start_services())
    except KeyboardInterrupt:
        logger.info("🛑 Services stopped by user")
        sys.exit(0)

