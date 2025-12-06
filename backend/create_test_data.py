#!/usr/bin/env python3
"""
Create test order data for the dashboard
Generates sample orders for testing and demonstration purposes
"""

import sqlite3
import json
from datetime import datetime, timedelta
import random

def create_test_data():
    """Create test order data in the database"""
    
    conn = sqlite3.connect('order_history.db')
    cursor = conn.cursor()
    
    # Create table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            client_oid TEXT,
            instrument_name TEXT,
            order_type TEXT,
            side TEXT,
            status TEXT,
            quantity REAL,
            price REAL,
            avg_price REAL,
            order_value REAL,
            cumulative_quantity REAL,
            cumulative_value REAL,
            create_time INTEGER,
            update_time INTEGER,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Test symbols
    symbols = ['BTC_USDT', 'ETH_USDT', 'BNB_USDT', 'SOL_USDT', 'ADA_USDT']
    sides = ['BUY', 'SELL']
    statuses_open = ['ACTIVE', 'PENDING']
    statuses_executed = ['FILLED', 'CANCELED', 'FILLED']
    
    base_time = int(datetime.now().timestamp() * 1000)
    
    print("Creating test orders...")
    
    # Create 5 open orders
    for i in range(1, 6):
        order_id = f"OPEN{i:04d}"
        symbol = random.choice(symbols)
        side = random.choice(sides)
        status = random.choice(statuses_open)
        
        # Random price based on symbol
        base_prices = {
            'BTC_USDT': 50000,
            'ETH_USDT': 3000,
            'BNB_USDT': 400,
            'SOL_USDT': 100,
            'ADA_USDT': 0.50
        }
        base_price = base_prices[symbol]
        price = base_price * (1 + random.uniform(-0.05, 0.05))
        quantity = random.uniform(0.001, 0.1)
        
        order_data = {
            'order_id': order_id,
            'instrument_name': symbol,
            'order_type': 'LIMIT',
            'side': side,
            'status': status,
            'quantity': quantity,
            'price': price,
            'avg_price': None,
            'order_value': quantity * price,
            'cumulative_quantity': 0,
            'cumulative_value': 0,
            'create_time': base_time - i * 3600000,  # 1 hour apart
            'update_time': base_time - i * 3600000
        }
        
        cursor.execute("""
            INSERT OR REPLACE INTO order_history 
            (order_id, instrument_name, order_type, side, status, quantity, price, 
             avg_price, order_value, cumulative_quantity, cumulative_value,
             create_time, update_time, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_data['order_id'],
            order_data['instrument_name'],
            order_data['order_type'],
            order_data['side'],
            order_data['status'],
            order_data['quantity'],
            order_data['price'],
            order_data['avg_price'],
            order_data['order_value'],
            order_data['cumulative_quantity'],
            order_data['cumulative_value'],
            order_data['create_time'],
            order_data['update_time'],
            json.dumps(order_data)
        ))
    
    print(f"  ✅ Created 5 OPEN orders")
    
    # Create 10 executed orders
    for i in range(1, 11):
        order_id = f"FILLED{i:04d}"
        symbol = random.choice(symbols)
        side = random.choice(sides)
        status = random.choice(statuses_executed)
        
        # Random price based on symbol
        base_prices = {
            'BTC_USDT': 50000,
            'ETH_USDT': 3000,
            'BNB_USDT': 400,
            'SOL_USDT': 100,
            'ADA_USDT': 0.50
        }
        base_price = base_prices[symbol]
        price = base_price * (1 + random.uniform(-0.10, 0.10))
        quantity = random.uniform(0.001, 0.1)
        
        # For filled orders, avg_price is set
        avg_price = price * (1 + random.uniform(-0.01, 0.01))
        
        order_data = {
            'order_id': order_id,
            'instrument_name': symbol,
            'order_type': random.choice(['MARKET', 'LIMIT']),
            'side': side,
            'status': status,
            'quantity': quantity,
            'price': price,
            'avg_price': avg_price,
            'order_value': quantity * price,
            'cumulative_quantity': quantity if status == 'FILLED' else 0,
            'cumulative_value': quantity * avg_price if status == 'FILLED' else 0,
            'create_time': base_time - (i + 5) * 3600000,  # Starting after open orders
            'update_time': base_time - (i + 5) * 3600000 + 300000  # Updated 5 min later
        }
        
        cursor.execute("""
            INSERT OR REPLACE INTO order_history 
            (order_id, instrument_name, order_type, side, status, quantity, price,
             avg_price, order_value, cumulative_quantity, cumulative_value,
             create_time, update_time, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_data['order_id'],
            order_data['instrument_name'],
            order_data['order_type'],
            order_data['side'],
            order_data['status'],
            order_data['quantity'],
            order_data['price'],
            order_data['avg_price'],
            order_data['order_value'],
            order_data['cumulative_quantity'],
            order_data['cumulative_value'],
            order_data['create_time'],
            order_data['update_time'],
            json.dumps(order_data)
        ))
    
    print(f"  ✅ Created 10 EXECUTED orders")
    
    conn.commit()
    conn.close()
    
    print("\n✅ Test data created successfully!")
    print(f"\nSummary:")
    print(f"  - 5 open orders (ACTIVE/PENDING)")
    print(f"  - 10 executed orders (FILLED/CANCELED)")
    print(f"  - Total: 15 orders")

if __name__ == '__main__':
    try:
        create_test_data()
        print("\n📊 You can now view these orders in the dashboard!")
        print("   Open Orders tab will show 5 open orders")
        print("   Executed Orders tab will show 10 executed orders")
    except Exception as e:
        print(f"\n❌ Error creating test data: {e}")
        import traceback
        traceback.print_exc()
