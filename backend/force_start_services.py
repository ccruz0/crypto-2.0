#!/usr/bin/env python3
"""
Force start all trading services
Run this script inside the container to manually start services
"""
import asyncio
import logging
import sys
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Start all services"""
    logger.info("=" * 80)
    logger.info("🚀 FORCE STARTING ALL TRADING SERVICES")
    logger.info("=" * 80)
    
    tasks = []
    
    try:
        # 1. Exchange Sync Service
        logger.info("🔧 Starting Exchange Sync Service...")
        from app.services.exchange_sync import exchange_sync_service
        if not exchange_sync_service.is_running:
            task1 = asyncio.create_task(exchange_sync_service.start())
            tasks.append(task1)
            logger.info("✅ Exchange Sync Service task created")
        else:
            logger.info("ℹ️  Exchange Sync Service already running")
        
        # Wait a bit to let it initialize
        await asyncio.sleep(2)
        
        # 2. Signal Monitor Service
        logger.info("🔧 Starting Signal Monitor Service...")
        from app.services.signal_monitor import signal_monitor_service
        if not signal_monitor_service.is_running:
            task2 = asyncio.create_task(signal_monitor_service.start())
            tasks.append(task2)
            logger.info("✅ Signal Monitor Service task created")
        else:
            logger.info("ℹ️  Signal Monitor Service already running")
        
        # 3. Trading Scheduler
        logger.info("🔧 Starting Trading Scheduler...")
        from app.services.scheduler import trading_scheduler
        if not trading_scheduler.running:
            task3 = asyncio.create_task(trading_scheduler.run_scheduler())
            tasks.append(task3)
            logger.info("✅ Trading Scheduler task created")
        else:
            logger.info("ℹ️  Trading Scheduler already running")
        
        logger.info("=" * 80)
        logger.info(f"✅ ALL SERVICES STARTED - {len(tasks)} tasks running")
        logger.info("=" * 80)
        
        # Wait a bit to let services initialize
        await asyncio.sleep(5)
        
        # Verify services are running
        logger.info("🔍 Verifying service status...")
        logger.info(f"  - Exchange Sync is_running: {exchange_sync_service.is_running}")
        logger.info(f"  - Signal Monitor is_running: {signal_monitor_service.is_running}")
        logger.info(f"  - Trading Scheduler running: {trading_scheduler.running}")
        
        # Keep running forever
        logger.info("💓 Services are active. Press Ctrl+C to stop.")
        
        while True:
            await asyncio.sleep(60)
            # Periodic health check
            logger.info(f"💓 Health check - Exchange: {exchange_sync_service.is_running}, Monitor: {signal_monitor_service.is_running}, Scheduler: {trading_scheduler.running}")
        
    except KeyboardInterrupt:
        logger.info("🛑 Stopping services...")
        exchange_sync_service.stop()
        signal_monitor_service.stop()
        trading_scheduler.stop()
        logger.info("✅ Services stopped")
    except Exception as e:
        logger.error(f"❌ Error starting services: {e}", exc_info=True)
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

