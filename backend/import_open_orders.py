#!/usr/bin/env python3
"""
Import open orders and trigger orders from CSV files
"""

import csv
import sqlite3
import os
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clear_existing_orders():
    """Clear all existing open orders and trigger orders"""
    db_path = os.path.join(os.path.dirname(__file__), 'order_history.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Clear open orders (status = 'open')
    cursor.execute("DELETE FROM order_history WHERE status = 'open'")
    open_deleted = cursor.rowcount
    
    # Clear trigger orders (order_type contains 'trigger' or 'take-profit' or 'stop-loss')
    cursor.execute("DELETE FROM order_history WHERE order_type LIKE '%trigger%' OR order_type LIKE '%Take-Profit%' OR order_type LIKE '%Stop-Loss%'")
    trigger_deleted = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    logger.info(f"Cleared {open_deleted} open orders and {trigger_deleted} trigger orders")
    return open_deleted + trigger_deleted

def import_open_orders(csv_file_path):
    """Import open orders from CSV file"""
    db_path = os.path.join(os.path.dirname(__file__), 'order_history.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Ensure table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE,
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
    
    imported_count = 0
    
    with open(csv_file_path, 'r', encoding='utf-8') as file:
        # Skip header lines
        for _ in range(4):  # Skip disclaimer, export info, and empty line
            next(file)
        
        reader = csv.DictReader(file, quotechar='"', delimiter=',')
        
        for row in reader:
            try:
                # Parse the order data
                instrument = row['Instrument'].replace('/', '_')
                order_type = row['Type']
                side = row['Side']
                price = float(row['Price']) if row['Price'] else 0.0
                quantity = float(row['Quantity'].replace(',', '')) if row['Quantity'] else 0.0
                remaining = float(row['Remaining'].replace(',', '')) if row['Remaining'] else 0.0
                order_value = float(row['Order Value'].replace(',', '')) if row['Order Value'] else 0.0
                avg_price = float(row['Average Price']) if row['Average Price'] else 0.0
                margin = row['Margin'] == 'True'
                tif = row['TIF']
                order_id = row['Order ID']
                
                # Parse timestamp
                time_str = row['Time']
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                create_time = int(dt.timestamp() * 1000)  # Convert to milliseconds
                
                # Determine status based on remaining quantity
                status = 'open' if remaining > 0 else 'filled'
                
                # Insert into database
                cursor.execute("""
                    INSERT OR REPLACE INTO order_history (
                        order_id, instrument_name, order_type, side, status,
                        quantity, price, avg_price, order_value, cumulative_quantity,
                        cumulative_value, create_time, update_time, raw_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id,
                    instrument,
                    order_type,
                    side,
                    status,
                    quantity,
                    price,
                    avg_price,
                    order_value,
                    quantity - remaining,  # cumulative_quantity
                    order_value * (quantity - remaining) / quantity if quantity > 0 else 0,  # cumulative_value
                    create_time,
                    create_time,
                    str(row)  # raw_data
                ))
                
                imported_count += 1
                logger.info(f"Imported open order: {instrument} {side} {quantity} @ {price}")
                
            except Exception as e:
                logger.error(f"Error importing order {row.get('Order ID', 'unknown')}: {e}")
                continue
    
    conn.commit()
    conn.close()
    return imported_count

def import_trigger_orders(csv_file_path):
    """Import trigger orders from CSV file"""
    db_path = os.path.join(os.path.dirname(__file__), 'order_history.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    imported_count = 0
    
    with open(csv_file_path, 'r', encoding='utf-8') as file:
        # Skip header lines
        for _ in range(4):  # Skip disclaimer, export info, and empty line
            next(file)
        
        reader = csv.DictReader(file, quotechar='"', delimiter=',')
        
        for row in reader:
            try:
                # Parse the order data
                instrument = row['Instrument'].replace('/', '_')
                order_type = row['Type']
                side = row['Side']
                price = float(row['Price']) if row['Price'] else 0.0
                quantity = float(row['Quantity'].replace(',', '')) if row['Quantity'] else 0.0
                order_value = float(row['Order Value'].replace(',', '')) if row['Order Value'] else 0.0
                trigger_condition = row['Trigger Condition']
                order_id = row['Order ID']
                
                # Parse timestamp
                time_str = row['Time']
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                create_time = int(dt.timestamp() * 1000)  # Convert to milliseconds
                
                # Insert into database
                cursor.execute("""
                    INSERT OR REPLACE INTO order_history (
                        order_id, instrument_name, order_type, side, status,
                        quantity, price, avg_price, order_value, cumulative_quantity,
                        cumulative_value, create_time, update_time, raw_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id,
                    instrument,
                    order_type,
                    side,
                    'trigger',  # status for trigger orders
                    quantity,
                    price,
                    0.0,  # avg_price
                    order_value,
                    0.0,  # cumulative_quantity
                    0.0,  # cumulative_value
                    create_time,
                    create_time,
                    str(row)  # raw_data
                ))
                
                imported_count += 1
                logger.info(f"Imported trigger order: {instrument} {side} {quantity} @ {price} ({trigger_condition})")
                
            except Exception as e:
                logger.error(f"Error importing trigger order {row.get('Order ID', 'unknown')}: {e}")
                continue
    
    conn.commit()
    conn.close()
    return imported_count

def main():
    """Main function to import orders"""
    try:
        # Clear existing orders
        cleared_count = clear_existing_orders()
        logger.info(f"Cleared {cleared_count} existing orders")
        
        # Import open orders
        open_orders_path = "/Users/carloscruz/Desktop/novale/open-orders.csv"
        if os.path.exists(open_orders_path):
            open_count = import_open_orders(open_orders_path)
            logger.info(f"Imported {open_count} open orders")
        else:
            logger.warning(f"Open orders file not found: {open_orders_path}")
        
        # Import trigger orders
        trigger_orders_path = "/Users/carloscruz/Desktop/novale/trigger-orders.csv"
        if os.path.exists(trigger_orders_path):
            trigger_count = import_trigger_orders(trigger_orders_path)
            logger.info(f"Imported {trigger_count} trigger orders")
        else:
            logger.warning(f"Trigger orders file not found: {trigger_orders_path}")
        
        logger.info("Order import completed successfully!")
        
    except Exception as e:
        logger.error(f"Error during import: {e}")
        raise

if __name__ == "__main__":
    main()
