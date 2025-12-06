#!/usr/bin/env python3
"""Analyze open BUY orders to find best candidates for liquidation"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.services.brokers.crypto_com_trade import trade_client
import requests
from collections import defaultdict

db = SessionLocal()
try:
    # Get all open BUY orders (exclude SL/TP)
    open_buy_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.side == OrderSideEnum.BUY,
        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
        ~ExchangeOrder.order_type.in_(['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT'])
    ).order_by(ExchangeOrder.exchange_create_time.desc()).all()
    
    print(f'📊 Found {len(open_buy_orders)} open BUY orders\n')
    
    if not open_buy_orders:
        print('No open BUY orders found.')
        exit(0)
    
    # Get current market prices
    print('🔍 Fetching current market prices...')
    tickers_response = trade_client.get_tickers()
    market_prices = {}
    
    if tickers_response and 'result' in tickers_response and 'data' in tickers_response['result']:
        for ticker in tickers_response['result']['data']:
            symbol = ticker.get('i', '')
            price = float(ticker.get('a', 0))  # last price
            if symbol and price > 0:
                market_prices[symbol] = price
    
    print(f'✅ Got prices for {len(market_prices)} symbols\n')
    
    # Analyze each order
    order_analysis = []
    
    for order in open_buy_orders:
        symbol = order.symbol
        current_price = market_prices.get(symbol, 0)
        
        # Get entry price
        entry_price = float(order.price or order.avg_price or order.filled_price or 0)
        if not entry_price:
            print(f'⚠️ Order {order.exchange_order_id} ({symbol}) has no price - skipping')
            continue
        
        # Get quantity
        quantity = float(order.quantity or order.filled_quantity or 0)
        if not quantity:
            print(f'⚠️ Order {order.exchange_order_id} ({symbol}) has no quantity - skipping')
            continue
        
        # Calculate P&L
        if current_price > 0:
            entry_value = entry_price * quantity
            current_value = current_price * quantity
            profit_usd = current_value - entry_value
            profit_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        else:
            entry_value = entry_price * quantity
            current_value = 0
            profit_usd = 0
            profit_pct = 0
            print(f'⚠️ No market price found for {symbol}')
        
        order_analysis.append({
            'order_id': order.exchange_order_id,
            'symbol': symbol,
            'quantity': quantity,
            'entry_price': entry_price,
            'current_price': current_price,
            'entry_value_usd': entry_value,
            'current_value_usd': current_value,
            'profit_usd': profit_usd,
            'profit_pct': profit_pct,
            'create_time': order.exchange_create_time or order.created_at
        })
    
    # Sort by profit (highest first)
    order_analysis.sort(key=lambda x: x['profit_usd'], reverse=True)
    
    print('=' * 80)
    print('📊 ANALYSIS: Orders sorted by profit (highest first)')
    print('=' * 80)
    
    total_value_usd = 0
    selected_orders = []
    target_liquidation = 10000  # USD
    
    for i, order in enumerate(order_analysis, 1):
        status = '✅ SELECTED' if total_value_usd < target_liquidation else ''
        
        print(f"\n{i}. {order['symbol']} {status}")
        print(f"   Order ID: {order['order_id']}")
        print(f"   Quantity: {order['quantity']:,.6f}")
        print(f"   Entry Price: ${order['entry_price']:,.6f}")
        print(f"   Current Price: ${order['current_price']:,.6f}")
        print(f"   Entry Value: ${order['entry_value_usd']:,.2f}")
        print(f"   Current Value: ${order['current_value_usd']:,.2f}")
        print(f"   Profit: ${order['profit_usd']:,.2f} ({order['profit_pct']:+.2f}%)")
        
        if total_value_usd < target_liquidation and order['current_value_usd'] > 0:
            selected_orders.append(order)
            total_value_usd += order['current_value_usd']
    
    print('\n' + '=' * 80)
    print('💰 LIQUIDATION PROPOSAL')
    print('=' * 80)
    
    if not selected_orders:
        print('❌ No orders found that meet criteria')
        exit(0)
    
    print(f'\nSelected {len(selected_orders)} orders for liquidation:')
    print(f'Total value to liquidate: ${total_value_usd:,.2f} USD\n')
    
    # Group by symbol to create combined sell orders
    symbol_orders = defaultdict(list)
    for order in selected_orders:
        symbol_orders[order['symbol']].append(order)
    
    print('📋 PROPOSED SELL ORDERS (MARKET):')
    print('-' * 80)
    
    liquidation_plan = []
    
    for symbol, orders in symbol_orders.items():
        total_quantity = sum(o['quantity'] for o in orders)
        avg_entry = sum(o['entry_price'] * o['quantity'] for o in orders) / total_quantity if total_quantity > 0 else 0
        current_price = orders[0]['current_price']
        total_profit = sum(o['profit_usd'] for o in orders)
        total_value = sum(o['current_value_usd'] for o in orders)
        
        liquidation_plan.append({
            'symbol': symbol,
            'quantity': total_quantity,
            'entry_price': avg_entry,
            'current_price': current_price,
            'total_profit': total_profit,
            'total_value': total_value,
            'order_ids': [o['order_id'] for o in orders]
        })
        
        print(f'\n{symbol}:')
        print(f'  Quantity to sell: {total_quantity:,.6f}')
        print(f'  Current price: ${current_price:,.6f}')
        print(f'  Total value: ${total_value:,.2f} USD')
        print(f'  Estimated profit: ${total_profit:,.2f} USD')
        print(f'  Affected order IDs: {", ".join(map(str, [o["order_id"] for o in orders]))}')
    
    print('\n' + '=' * 80)
    print(f'💰 TOTAL: ${total_value_usd:,.2f} USD to liquidate')
    print(f'📈 Estimated total profit: ${sum(p["total_profit"] for p in liquidation_plan):,.2f} USD')
    print('=' * 80)
    
    # Save plan to file for execution script
    import json
    plan_file = '/tmp/liquidation_plan.json'
    with open(plan_file, 'w') as f:
        json.dump(liquidation_plan, f, indent=2, default=str)
    
    print(f'\n✅ Liquidation plan saved to: {plan_file}')
    print('⚠️  Review the plan above before executing!')
    
finally:
    db.close()

