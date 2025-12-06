#!/usr/bin/env python3
"""
DEBUG ONLY – DO NOT RUN IN PRODUCTION

This script starts SignalMonitorService as a standalone process.
It is ONLY for debugging purposes.

⚠️ WARNING: Do NOT run this in production because:
- SignalMonitorService is already started by the main FastAPI app (backend/app/main.py)
- Running this would create a duplicate monitor instance
- This would cause duplicate alerts, duplicate orders, and data inconsistencies
- In production, only the AWS backend container should run SignalMonitorService

Use this script ONLY for:
- Local debugging when the main app is not running
- Testing SignalMonitorService in isolation
- Development scenarios where you need to debug the monitor separately

For production, SignalMonitorService is automatically started by the FastAPI app.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.signal_monitor import signal_monitor_service
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.warning("⚠️  DEBUG MODE: Starting Signal Monitor Service as standalone process")
    logger.warning("⚠️  This should ONLY be used for debugging, not in production")
    logger.info("🚀 Starting Signal Monitor Service")
    await signal_monitor_service.start()

if __name__ == "__main__":
    asyncio.run(main())
