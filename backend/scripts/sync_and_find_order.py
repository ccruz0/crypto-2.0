#!/usr/bin/env python3
"""
Script to sync orders from Crypto.com and find a specific order
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.services.exchange_sync import exchange_sync_service
from app.services.brokers.crypto_com_trade import trade_client
from app.utils.live_trading import get_live_trading_status
from app.models.exchange_order import ExchangeOrder
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Force enable live trading
os.environ['LIVE_TRADING'] = 'true'
trade_client.live_trading = True

def sync_and_find_order(order_id: str):
    """Sync orders and find the specific order"""
    db = SessionLocal()
    try:
        # Check LIVE_TRADING status
        live_status = get_live_trading_status(db)
        print(f'LIVE_TRADING from database: {live_status}')
        print(f'Trade client LIVE_TRADING: {trade_client.live_trading}')
        print(f'API Key configured: {"Yes" if trade_client.api_key else "No"}')
        print(f'Using proxy: {trade_client.use_proxy}')
        
        if not trade_client.api_key and not trade_client.use_proxy:
            print('\n⚠️  API credentials not configured and proxy not enabled')
            print('   Cannot fetch real orders from Crypto.com')
            print('   Please configure EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET')
            print('   Or enable USE_CRYPTO_PROXY=true')
            return None
        else:
            print(f'\n🔄 Syncing order history to find order {order_id}...')
            # Sync with more pages to find the order
            exchange_sync_service.sync_order_history(db, page_size=200, max_pages=20)
            
            # Check if order is now in database
            order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == order_id
            ).first()
            
            if order:
                print(f'\n✅ Order found in database after sync:')
                print(f'   Order ID: {order.exchange_order_id}')
                print(f'   Symbol: {order.symbol}')
                print(f'   Side: {order.side.value}')
                print(f'   Status: {order.status.value}')
                print(f'   Price: {order.price or order.avg_price}')
                print(f'   Quantity: {order.quantity or order.cumulative_quantity}')
                print(f'   Avg Price: {order.avg_price}')
                print(f'   Cumulative Qty: {order.cumulative_quantity}')
                return order
            else:
                print(f'\n❌ Order {order_id} still not found')
                print(f'   It may be very recent, still open, or the order ID might be incorrect')
                return None
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 sync_and_find_order.py <order_id>")
        sys.exit(1)
    
    order_id = sys.argv[1]
    order = sync_and_find_order(order_id)
    sys.exit(0 if order else 1)


