#!/usr/bin/env python3
"""
Script to find a specific order from Crypto.com Exchange
"""
import sys
import os
from pathlib import Path

# Load credentials from .env.local BEFORE importing anything
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
project_root = os.path.dirname(backend_dir)
env_file = Path(project_root) / '.env.local'

if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value
    print("✅ Loaded credentials from .env.local")

# CRITICAL: Set LIVE_TRADING before importing trade_client
os.environ['LIVE_TRADING'] = 'true'

# Add to path
sys.path.insert(0, backend_dir)

# Check database for LIVE_TRADING status first
from app.database import SessionLocal
from app.utils.live_trading import get_live_trading_status

db = SessionLocal()
try:
    live_trading_status = get_live_trading_status(db)
    if live_trading_status:
        print("✅ LIVE_TRADING is enabled in database")
    else:
        print("⚠️  LIVE_TRADING was disabled in database, enabling for this search...")
finally:
    db.close()

# Now import and create a NEW trade_client instance (it will read credentials from env)
from app.services.brokers.crypto_com_trade import CryptoComTradeClient
trade_client = CryptoComTradeClient()
trade_client.live_trading = True
import logging
import time
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def find_order_in_crypto(order_id: str):
    """Search for order in Crypto.com Exchange"""
    
    # Force enable live trading on the trade_client instance
    trade_client.live_trading = True
    logger.info(f"Trade client LIVE_TRADING status: {trade_client.live_trading}")
    logger.info(f"API Key configured: {'Yes' if trade_client.api_key else 'No'}")
    logger.info(f"API Secret configured: {'Yes' if trade_client.api_secret else 'No'}")
    
    if not trade_client.api_key or not trade_client.api_secret:
        logger.warning("⚠️  API credentials not configured - cannot fetch real orders from Crypto.com")
        logger.warning("   Please set EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET environment variables")
        return None
    
    logger.info(f"🔍 Searching for order {order_id} in Crypto.com Exchange...")
    
    # First check open orders
    logger.info("Checking open orders...")
    try:
        open_orders_result = trade_client.get_open_orders()
        open_orders = open_orders_result.get('data', []) if open_orders_result else []
        
        for order in open_orders:
            if str(order.get('order_id', '')) == order_id:
                print(f"\n✅ Found order in OPEN orders:")
                print(f"   Order ID: {order.get('order_id')}")
                print(f"   Symbol: {order.get('instrument_name')}")
                print(f"   Side: {order.get('side')}")
                print(f"   Status: {order.get('status')}")
                print(f"   Type: {order.get('order_type')}")
                print(f"   Price: {order.get('limit_price') or order.get('price')}")
                print(f"   Quantity: {order.get('quantity')}")
                print(f"   Create Time: {datetime.fromtimestamp(order.get('create_time', 0) / 1000) if order.get('create_time') else 'N/A'}")
                return order
    except Exception as e:
        logger.warning(f"Error checking open orders: {e}")
    
    # Check trigger orders
    logger.info("Checking trigger orders...")
    try:
        trigger_orders_result = trade_client.get_trigger_orders()
        trigger_orders = trigger_orders_result.get('data', []) if trigger_orders_result else []
        
        for order in trigger_orders:
            if str(order.get('order_id', '')) == order_id:
                print(f"\n✅ Found order in TRIGGER orders:")
                print(f"   Order ID: {order.get('order_id')}")
                print(f"   Symbol: {order.get('instrument_name')}")
                print(f"   Side: {order.get('side')}")
                print(f"   Status: {order.get('status')}")
                print(f"   Type: {order.get('order_type')}")
                print(f"   Price: {order.get('limit_price') or order.get('price')}")
                print(f"   Quantity: {order.get('quantity')}")
                return order
    except Exception as e:
        logger.warning(f"Error checking trigger orders: {e}")
    
    # Search in order history - go back up to 90 days
    logger.info("Searching order history (this may take a while)...")
    found_order = None
    
    # Search in chunks: last 7 days, then 7-30 days, then 30-90 days
    search_ranges = [
        (0, 7),    # Last 7 days
        (7, 30),   # 7-30 days ago
        (30, 90),  # 30-90 days ago
    ]
    
    for days_start, days_end in search_ranges:
        if found_order:
            break
            
        logger.info(f"Searching orders from {days_end} to {days_start} days ago...")
        
        end_time_ms = int((datetime.now() - timedelta(days=days_start)).timestamp() * 1000)
        start_time_ms = int((datetime.now() - timedelta(days=days_end)).timestamp() * 1000)
        
        # Search multiple pages
        for page in range(10):  # Search up to 10 pages
            try:
                history_result = trade_client.get_order_history(
                    page_size=200,
                    start_time=start_time_ms,
                    end_time=end_time_ms,
                    page=page
                )
                
                orders = history_result.get('data', []) if history_result else []
                
                if not orders:
                    break
                
                for order in orders:
                    if str(order.get('order_id', '')) == order_id:
                        found_order = order
                        break
                
                if found_order:
                    break
                    
                # If we got fewer orders than page_size, we've reached the end
                if len(orders) < 200:
                    break
                    
            except Exception as e:
                logger.warning(f"Error fetching page {page}: {e}")
                break
    
    if found_order:
        print(f"\n✅ Found order in HISTORY:")
        print(f"   Order ID: {found_order.get('order_id')}")
        print(f"   Symbol: {found_order.get('instrument_name')}")
        print(f"   Side: {found_order.get('side')}")
        print(f"   Status: {found_order.get('status')}")
        print(f"   Type: {found_order.get('order_type')}")
        print(f"   Price: {found_order.get('limit_price') or found_order.get('price') or found_order.get('avg_price')}")
        print(f"   Quantity: {found_order.get('quantity')}")
        print(f"   Cumulative Quantity: {found_order.get('cumulative_quantity')}")
        print(f"   Avg Price: {found_order.get('avg_price')}")
        if found_order.get('create_time'):
            print(f"   Create Time: {datetime.fromtimestamp(found_order['create_time'] / 1000)}")
        if found_order.get('update_time'):
            print(f"   Update Time: {datetime.fromtimestamp(found_order['update_time'] / 1000)}")
        return found_order
    else:
        print(f"\n❌ Order {order_id} not found in Crypto.com Exchange")
        print(f"   Searched:")
        print(f"   - Open orders")
        print(f"   - Trigger orders")
        print(f"   - Order history (last 90 days)")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 find_order_crypto.py <order_id>")
        sys.exit(1)
    
    order_id = sys.argv[1]
    order = find_order_in_crypto(order_id)
    sys.exit(0 if order else 1)


