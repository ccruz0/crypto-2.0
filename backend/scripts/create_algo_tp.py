#!/usr/bin/env python3
"""
Script to create a Take Profit order for ALGO with 2% profit based on buy price.
"""
import sys
import os

# Add the parent directory to the path so we can import from app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.services.portfolio_cache import get_portfolio_summary
from app.services.expected_take_profit import get_expected_take_profit_summary
from app.services.tp_sl_order_creator import create_take_profit_order
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.utils.live_trading import get_live_trading_status

def main():
    db = SessionLocal()
    try:
        # Get live trading status
        live_trading = get_live_trading_status(db)
        dry_run = not live_trading
        
        print(f"Mode: {'DRY RUN' if dry_run else 'LIVE TRADING'}")
        print("=" * 60)
        
        # Get ALGO balance and info
        portfolio = get_portfolio_summary(db)
        balances = portfolio.get('balances', [])
        
        algo_balance = None
        for bal in balances:
            if bal.get('currency', '').upper() == 'ALGO':
                algo_balance = bal
                break
        
        if not algo_balance:
            print("❌ Error: ALGO balance not found in portfolio")
            return 1
        
        balance = float(algo_balance.get('balance', 0))
        value_usd = float(algo_balance.get('usd_value', 0))
        current_price = value_usd / balance if balance > 0 else 0
        
        print(f"ALGO Balance: {balance:.2f}")
        print(f"Current Price: ${current_price:.6f}")
        
        # Get buy price from Expected Take Profit
        portfolio_assets = [{'coin': 'ALGO', 'balance': balance, 'value_usd': value_usd}]
        market_prices = {'ALGO': current_price}
        summary = get_expected_take_profit_summary(db, portfolio_assets, market_prices)
        
        algo_summary = summary.get('ALGO') or summary.get('ALGO_USDT')
        if not algo_summary:
            print("❌ Error: Could not get ALGO summary from Expected Take Profit")
            return 1
        
        net_qty = float(algo_summary.get('net_qty', 0))
        actual_position_value = float(algo_summary.get('actual_position_value', 0))
        buy_price = actual_position_value / net_qty if net_qty > 0 else current_price
        
        print(f"\nBuy Price: ${buy_price:.6f}")
        print(f"Net Quantity: {net_qty:.2f}")
        
        # Calculate TP with 2% profit
        tp_price = buy_price * 1.02
        
        print(f"\nTP Order Details:")
        print(f"  Symbol: ALGO_USDT")
        print(f"  TP Price (2% profit): ${tp_price:.6f}")
        print(f"  Quantity: {net_qty:.2f}")
        print(f"  Expected Profit: ${(tp_price - buy_price) * net_qty:.2f}")
        
        # Find most recent BUY order for ALGO_USDT to use as parent
        orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol.in_(['ALGO_USDT', 'ALGO_USD', 'ALGO']),
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED
        ).order_by(ExchangeOrder.exchange_create_time.desc()).all()
        
        recent_buy = None
        for order in orders:
            price = order.avg_price or order.price
            if (not price or price == 0) and hasattr(order, 'cumulative_value') and hasattr(order, 'cumulative_quantity'):
                if order.cumulative_quantity and order.cumulative_quantity > 0:
                    if order.cumulative_value and order.cumulative_value > 0:
                        price = order.cumulative_value / order.cumulative_quantity
            if price and price > 0:
                recent_buy = order
                break
        
        if not recent_buy:
            print("❌ Error: Could not find a recent BUY order for ALGO")
            return 1
        
        print(f"\nParent Order:")
        print(f"  Order ID: {recent_buy.exchange_order_id}")
        print(f"  Symbol: {recent_buy.symbol}")
        
        # Confirm before creating (unless dry_run)
        if not dry_run:
            print("\n⚠️  LIVE TRADING MODE - Creating TP order...")
            # Note: In non-interactive mode, we proceed directly. 
            # If you want to cancel, stop the script before this point.
        
        # Create TP order
        print(f"\nCreating TP order...")
        result = create_take_profit_order(
            db=db,
            symbol="ALGO_USDT",
            side="BUY",  # Original order side
            tp_price=tp_price,
            quantity=net_qty,
            entry_price=buy_price,
            parent_order_id=recent_buy.exchange_order_id,
            oco_group_id=recent_buy.oco_group_id,
            is_margin=False,
            dry_run=dry_run,
            source="manual"
        )
        
        if result.get("error"):
            print(f"❌ Error creating TP order: {result['error']}")
            return 1
        else:
            print(f"\n✅ TP order created successfully!")
            print(f"   Order ID: {result.get('order_id', 'N/A')}")
            return 0
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

if __name__ == "__main__":
    sys.exit(main())

