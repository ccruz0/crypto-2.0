#!/usr/bin/env python3
"""
Manual service starter - to be run inside the container
This script starts all trading services manually
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

