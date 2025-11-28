#!/usr/bin/env python3
"""Start signal monitor service as a standalone process"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.signal_monitor import signal_monitor_service
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("🚀 Starting Signal Monitor Service")
    await signal_monitor_service.start()

if __name__ == "__main__":
    asyncio.run(main())
