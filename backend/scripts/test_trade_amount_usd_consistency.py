#!/usr/bin/env python3
"""
Test script to verify trade_amount_usd consistency between DB and API.

This script:
1. Inserts a WatchlistItem with trade_amount_usd = NULL
2. Calls GET /api/dashboard
3. Asserts response includes trade_amount_usd === null (not 10)
4. Inserts a WatchlistItem with trade_amount_usd = 10.0
5. Asserts API returns exactly 10.0 (not 11)
"""

import sys
import os
from pathlib import Path
import requests
from typing import Dict, Any

# Add parent directory to path to import app modules
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_null_trade_amount_usd(api_url: str = "http://localhost:8002/api/dashboard"):
    """Test that NULL trade_amount_usd in DB returns null in API (not 10)"""
    db: Session = SessionLocal()
    try:
        # Create test item with NULL trade_amount_usd
        test_symbol = "TEST_NULL_USD"
        
        # Clean up any existing test item
        existing = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == test_symbol
        ).first()
        if existing:
            db.delete(existing)
            db.commit()
        
        # Create new item with NULL trade_amount_usd
        test_item = WatchlistItem(
            symbol=test_symbol,
            exchange="CRYPTO_COM",
            trade_amount_usd=None,  # Explicitly NULL
            is_deleted=False
        )
        db.add(test_item)
        db.commit()
        db.refresh(test_item)
        
        logger.info(f"Created test item: {test_symbol} with trade_amount_usd=None")
        
        # Fetch from API
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        api_items = response.json()
        
        # Find our test item
        test_item_api = None
        for item in api_items:
            if item.get("symbol") == test_symbol:
                test_item_api = item
                break
        
        if not test_item_api:
            raise AssertionError(f"Test item {test_symbol} not found in API response")
        
        # CRITICAL: Assert trade_amount_usd is null (not 10, not 0, not any default)
        api_value = test_item_api.get("trade_amount_usd")
        if api_value is not None:
            raise AssertionError(
                f"FAILED: trade_amount_usd should be null, but API returned: {api_value} (type: {type(api_value)})"
            )
        
        logger.info(f"✅ PASSED: trade_amount_usd is null as expected")
        
        # Clean up
        db.delete(test_item)
        db.commit()
        
        return True
        
    except Exception as e:
        db.rollback()
        logger.error(f"Test failed: {e}", exc_info=True)
        # Clean up on error
        try:
            test_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == test_symbol
            ).first()
            if test_item:
                db.delete(test_item)
                db.commit()
        except:
            pass
        raise
    finally:
        db.close()


def test_exact_value_trade_amount_usd(api_url: str = "http://localhost:8002/api/dashboard"):
    """Test that trade_amount_usd = 10.0 in DB returns exactly 10.0 in API (not 11)"""
    db: Session = SessionLocal()
    try:
        # Create test item with trade_amount_usd = 10.0
        test_symbol = "TEST_10_USD"
        
        # Clean up any existing test item
        existing = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == test_symbol
        ).first()
        if existing:
            db.delete(existing)
            db.commit()
        
        # Create new item with trade_amount_usd = 10.0
        test_item = WatchlistItem(
            symbol=test_symbol,
            exchange="CRYPTO_COM",
            trade_amount_usd=10.0,  # Explicitly 10.0
            is_deleted=False
        )
        db.add(test_item)
        db.commit()
        db.refresh(test_item)
        
        logger.info(f"Created test item: {test_symbol} with trade_amount_usd=10.0")
        
        # Fetch from API
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        api_items = response.json()
        
        # Find our test item
        test_item_api = None
        for item in api_items:
            if item.get("symbol") == test_symbol:
                test_item_api = item
                break
        
        if not test_item_api:
            raise AssertionError(f"Test item {test_symbol} not found in API response")
        
        # CRITICAL: Assert trade_amount_usd is exactly 10.0 (not 11, not any other value)
        api_value = test_item_api.get("trade_amount_usd")
        if api_value != 10.0:
            raise AssertionError(
                f"FAILED: trade_amount_usd should be 10.0, but API returned: {api_value} (type: {type(api_value)})"
            )
        
        logger.info(f"✅ PASSED: trade_amount_usd is exactly 10.0 as expected")
        
        # Clean up
        db.delete(test_item)
        db.commit()
        
        return True
        
    except Exception as e:
        db.rollback()
        logger.error(f"Test failed: {e}", exc_info=True)
        # Clean up on error
        try:
            test_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == test_symbol
            ).first()
            if test_item:
                db.delete(test_item)
                db.commit()
        except:
            pass
        raise
    finally:
        db.close()


def main():
    """Run all tests"""
    try:
        # Try to determine API URL from environment or use default
        api_url = os.getenv("API_URL", "http://localhost:8002/api/dashboard")
        if not api_url.endswith("/api/dashboard"):
            api_url = f"{api_url.rstrip('/')}/api/dashboard"
        
        logger.info(f"Using API URL: {api_url}")
        
        # Test 1: NULL value
        logger.info("=" * 60)
        logger.info("Test 1: NULL trade_amount_usd should return null")
        logger.info("=" * 60)
        test_null_trade_amount_usd(api_url)
        
        # Test 2: Exact value
        logger.info("=" * 60)
        logger.info("Test 2: trade_amount_usd=10.0 should return exactly 10.0")
        logger.info("=" * 60)
        test_exact_value_trade_amount_usd(api_url)
        
        logger.info("=" * 60)
        logger.info("✅ ALL TESTS PASSED")
        logger.info("=" * 60)
        return 0
        
    except Exception as e:
        logger.error(f"Tests failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

