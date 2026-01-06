#!/usr/bin/env python3
"""
Run one evaluation cycle of the signal monitor.

Usage:
    DIAG_SYMBOL=ETH_USDT python scripts/run_one_cycle.py

This runs exactly one monitor iteration and exits.
"""

import os
import sys
import asyncio
import logging

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.services.signal_monitor import signal_monitor_service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def run_one_cycle():
    """Run one evaluation cycle"""
    db = SessionLocal()
    try:
        logger.info("🔄 Running one evaluation cycle...")
        await signal_monitor_service.monitor_signals(db)
        logger.info("✅ Evaluation cycle complete")
    except Exception as e:
        logger.error(f"❌ Error in evaluation cycle: {e}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_one_cycle())




