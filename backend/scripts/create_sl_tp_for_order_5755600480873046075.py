#!/usr/bin/env python3
"""
Create SL/TP orders for order 5755600480873046075
Based on screenshot details:
- Order ID: 5755600480873046075
- BTC/USD, Buy, Limit
- Price: 86,076.99
- Quantity: 0.11617 (filled)
- Status: Filled
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# Load environment variables
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

# Set LIVE_TRADING before importing
os.environ['LIVE_TRADING'] = 'true'
sys.path.insert(0, backend_dir)

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.models.trading_settings import TradingSettings
from app.services.exchange_sync import ExchangeSyncService
from app.utils.live_trading import get_live_trading_status
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Order details from screenshot
ORDER_ID = "5755600480873046075"
SYMBOL = "BTC_USD"  # Note: Crypto.com uses BTC_USD, not BTC_USDT
SIDE = "BUY"
PRICE = 86076.99
QUANTITY = 0.11617
ORDER_TYPE = "LIMIT"
STATUS = "FILLED"

def set_live_trading(db, enable: bool):
    """Set live trading in database"""
    setting = db.query(TradingSettings).first()
    if not setting:
        setting = TradingSettings(live_trading=enable)
        db.add(setting)
    else:
        setting.live_trading = enable
    db.commit()
    logger.info(f"✅ Set LIVE_TRADING in database to: {enable}")

def create_or_find_order(db):
    """Create the order record in database if it doesn't exist"""
    # Check if order already exists
    existing = db.query(ExchangeOrder).filter(
        ExchangeOrder.exchange_order_id == ORDER_ID
    ).first()
    
    if existing:
        logger.info(f"✅ Order {ORDER_ID} already exists in database")
        return existing
    
    # Create the order record
    logger.info(f"Creating order record for {ORDER_ID}...")
    order = ExchangeOrder(
        exchange_order_id=ORDER_ID,
        symbol=SYMBOL,
        side=OrderSideEnum.BUY,
        order_type="LIMIT",
        status=OrderStatusEnum.FILLED,
        price=PRICE,
        quantity=QUANTITY,
        cumulative_quantity=QUANTITY,  # Fully filled
        avg_price=PRICE,  # Same as price for limit orders
        exchange="CRYPTO_COM",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        order_role=None,  # This is the main order
        parent_order_id=None,
        is_margin=False,  # Default to spot
        leverage=None
    )
    
    db.add(order)
    db.commit()
    db.refresh(order)
    logger.info(f"✅ Created order record: {ORDER_ID}")
    return order

def main():
    db = SessionLocal()
    try:
        # Step 1: Enable live trading
        logger.info("=" * 60)
        logger.info("Step 1: Enabling live trading...")
        set_live_trading(db, True)
        os.environ['LIVE_TRADING'] = 'true'
        
        # Step 2: Create or find the order
        logger.info("=" * 60)
        logger.info("Step 2: Creating/finding order in database...")
        order = create_or_find_order(db)
        
        # Step 3: Create SL/TP orders
        logger.info("=" * 60)
        logger.info("Step 3: Creating SL/TP orders...")
        logger.info(f"Order details:")
        logger.info(f"  Symbol: {SYMBOL}")
        logger.info(f"  Side: {SIDE}")
        logger.info(f"  Price: {PRICE}")
        logger.info(f"  Quantity: {QUANTITY}")
        
        exchange_sync_service = ExchangeSyncService()
        exchange_sync_service._create_sl_tp_for_filled_order(
            db=db,
            symbol=SYMBOL,
            side=SIDE,
            filled_price=PRICE,
            filled_qty=QUANTITY,
            order_id=ORDER_ID
        )
        
        logger.info("=" * 60)
        logger.info("✅ SL/TP creation completed!")
        
        # Step 4: Disable live trading
        logger.info("=" * 60)
        logger.info("Step 4: Disabling live trading...")
        set_live_trading(db, False)
        os.environ['LIVE_TRADING'] = 'false'
        
        logger.info("=" * 60)
        logger.info("✅ All steps completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        # Try to disable live trading even on error
        try:
            set_live_trading(db, False)
            os.environ['LIVE_TRADING'] = 'false'
        except:
            pass
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()


