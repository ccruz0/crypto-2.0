#!/usr/bin/env python3
"""
Market Data Updater - Separate Worker Process
Run this as a separate process to update market data from external APIs.

Usage:
    python3 run_updater.py

This worker:
- Fetches data from external APIs (Crypto.com, CoinGecko, etc.)
- Respects rate limits (3s delay between coins)
- Saves results to shared storage (market_cache.json)
- Updates every 60 seconds
"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(__file__))

from market_updater import run_updater
import asyncio

if __name__ == "__main__":
    print("Starting market data updater worker...")
    print("Press Ctrl+C to stop")
    try:
        asyncio.run(run_updater())
    except KeyboardInterrupt:
        print("\nUpdater stopped by user")

