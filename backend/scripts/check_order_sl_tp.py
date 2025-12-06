#!/usr/bin/env python3
"""
Check SL/TP status for a specific order ID
Usage: python check_order_sl_tp.py <order_id>
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.brokers.crypto_com_trade import trade_client
from sqlalchemy import or_, text

def check_order_sl_tp(order_id: str):
    """Check SL/TP status for a specific order"""
    db = None
    order = None
    
    # Try to connect to database (with timeout handling)
    if SessionLocal is None:
        print("⚠️  Database not available (SessionLocal is None)")
        print("   Will check exchange API only...\n")
    else:
        try:
            db = SessionLocal()
            # Test connection with a simple query
            db.execute(text("SELECT 1"))
        except Exception as db_error:
            print(f"⚠️  Could not connect to database: {db_error}")
            print("   Will check exchange API only...\n")
            if db:
                try:
                    db.close()
                except:
                    pass
                db = None
    
    try:
        # Find the order in database (if DB available)
        if db:
            try:
                order = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == order_id
                ).first()
            except Exception as query_error:
                print(f"⚠️  Error querying database: {query_error}")
                db = None  # Mark DB as unavailable
        
        if not order:
            print(f"❌ Order {order_id} not found in database")
            print("\nTrying to fetch from exchange...")
            
            # Try to get order from exchange
            try:
                order_details = trade_client.get_order_detail(order_id)
                if order_details and order_details.get('result'):
                    order_data = order_details['result']
                    print(f"✅ Found order on exchange:")
                    print(f"   Symbol: {order_data.get('instrument_name')}")
                    print(f"   Side: {order_data.get('side')}")
                    print(f"   Type: {order_data.get('order_type')}")
                    print(f"   Status: {order_data.get('status')}")
                    print(f"   Price: {order_data.get('price')}")
                    print(f"   Quantity: {order_data.get('quantity')}")
                    print(f"   Filled: {order_data.get('cumulative_quantity', 0)}")
                    
                    # Check for SL/TP orders on exchange
                    symbol = order_data.get('instrument_name', '').replace('/', '_')
                    check_exchange_sl_tp(symbol, order_id)
                else:
                    print(f"❌ Order {order_id} not found on exchange either")
            except Exception as e:
                print(f"❌ Error fetching order from exchange: {e}")
            return
        
        # Order found in database
        print(f"✅ Order found in database:")
        print(f"   Order ID: {order.exchange_order_id}")
        print(f"   Symbol: {order.symbol}")
        print(f"   Side: {order.side}")
        print(f"   Type: {order.order_type}")
        print(f"   Status: {order.status}")
        print(f"   Price: {order.price}")
        print(f"   Quantity: {order.quantity}")
        print(f"   Filled: {order.cumulative_quantity or 0}")
        print(f"   Created: {order.created_at}")
        
        # Check for SL/TP orders linked to this order (if DB available)
        sl_orders = []
        tp_orders = []
        if db:
            sl_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order_id,
                ExchangeOrder.order_role == "STOP_LOSS",
                ExchangeOrder.status.in_([
                    OrderStatusEnum.NEW,
                    OrderStatusEnum.ACTIVE,
                    OrderStatusEnum.PENDING,
                    OrderStatusEnum.PARTIALLY_FILLED
                ])
            ).all()
            
            tp_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order_id,
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.status.in_([
                    OrderStatusEnum.NEW,
                    OrderStatusEnum.ACTIVE,
                    OrderStatusEnum.PENDING,
                    OrderStatusEnum.PARTIALLY_FILLED
                ])
            ).all()
        
        print(f"\n📊 SL/TP Status (from database):")
        print(f"   SL Orders: {len(sl_orders)}")
        if sl_orders:
            for sl in sl_orders:
                print(f"      - {sl.exchange_order_id}: {sl.status} | Price: {sl.price} | Trigger: {sl.trigger_condition}")
        else:
            print(f"      ❌ No active SL orders found")
        
        print(f"   TP Orders: {len(tp_orders)}")
        if tp_orders:
            for tp in tp_orders:
                print(f"      - {tp.exchange_order_id}: {tp.status} | Price: {tp.price} | Trigger: {tp.trigger_condition}")
        else:
            print(f"      ❌ No active TP orders found")
        
        # Also check exchange directly for more accurate status
        print(f"\n📊 SL/TP Status (from exchange API):")
        check_exchange_sl_tp(order.symbol, order_id)
        
        # Summary
        print(f"\n📋 Summary:")
        if len(sl_orders) > 0 and len(tp_orders) > 0:
            print(f"   ✅ Order has both SL and TP protection")
        elif len(sl_orders) > 0:
            print(f"   ⚠️  Order has SL but missing TP")
        elif len(tp_orders) > 0:
            print(f"   ⚠️  Order has TP but missing SL")
        else:
            print(f"   ❌ Order is missing both SL and TP protection")
            print(f"   💡 Use /create_sl_tp command in Telegram or run create_missing_tp_orders.py")
        
    except Exception as e:
        print(f"❌ Error checking order: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if db:
            db.close()

def check_exchange_sl_tp(symbol: str, parent_order_id: str):
    """Check SL/TP orders directly from exchange API"""
    try:
        # Get all open orders
        all_open_orders = trade_client.get_open_orders()
        all_orders_data = all_open_orders.get('data', [])
        
        # Normalize symbol (handle both BONK/USD and BONK_USD)
        symbol_normalized = symbol.replace('/', '_').upper()
        symbol_variants = [symbol_normalized]
        if symbol_normalized.endswith('_USDT'):
            symbol_variants.append(symbol_normalized.replace('_USDT', '_USD'))
        elif symbol_normalized.endswith('_USD'):
            symbol_variants.append(symbol_normalized.replace('_USD', '_USDT'))
        
        # Filter orders for this symbol
        symbol_orders = []
        for order in all_orders_data:
            order_instrument = order.get('instrument_name', '')
            order_symbol_normalized = order_instrument.replace('/', '_').upper()
            if order_symbol_normalized in symbol_variants or \
               any(v.replace('_', '/') == order_instrument for v in symbol_variants):
                symbol_orders.append(order)
        
        # Check for SL/TP orders
        sl_orders = []
        tp_orders = []
        
        for o in symbol_orders:
            order_type = o.get('order_type', '').lower()
            trigger_price = o.get('trigger_price')
            side = o.get('side', '')
            
            # Check for SL orders
            is_sl = False
            if any(sl_term in order_type for sl_term in ['stop', 'stop_loss', 'stop_loss_limit']):
                is_sl = True
            elif order_type == 'limit' and trigger_price and side.upper() == 'SELL':
                is_sl = True
            
            if is_sl:
                sl_orders.append(o)
            
            # Check for TP orders
            if any(tp_term in order_type for tp_term in ['take-profit', 'take_profit', 'take profit', 'profit_limit']) or \
               ('profit' in order_type and 'take' in order_type):
                tp_orders.append(o)
        
        print(f"   SL Orders on Exchange: {len(sl_orders)}")
        if sl_orders:
            for sl in sl_orders:
                print(f"      - {sl.get('order_id')}: {sl.get('order_type')} | Price: {sl.get('price')} | Trigger: {sl.get('trigger_price')}")
        else:
            print(f"      ❌ No SL orders found on exchange")
        
        print(f"   TP Orders on Exchange: {len(tp_orders)}")
        if tp_orders:
            for tp in tp_orders:
                print(f"      - {tp.get('order_id')}: {tp.get('order_type')} | Price: {tp.get('price')} | Trigger: {tp.get('trigger_price')}")
        else:
            print(f"      ❌ No TP orders found on exchange")
            
    except Exception as e:
        print(f"   ⚠️  Error checking exchange: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_order_sl_tp.py <order_id>")
        sys.exit(1)
    
    order_id = sys.argv[1]
    check_order_sl_tp(order_id)

