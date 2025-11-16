#!/usr/bin/env python3
"""
Import executed orders from CSV file into the order_history database

IMPORTANT: This script NEVER deletes existing data.
- Uses INSERT OR REPLACE to add new orders or update existing ones
- Historical data is preserved permanently
- CSV imports only ADD or UPDATE records, never DELETE
"""

import csv
import sys
import sqlite3
from datetime import datetime
import json

def parse_csv_and_import(csv_file_path):
    """Parse CSV file and import orders into database"""
    
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
    
    imported_count = 0
    error_count = 0
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as f:
            # Read all lines
            lines = f.readlines()
            
            # Find the actual header row (contains "Order ID")
            header_index = None
            for i, line in enumerate(lines):
                if 'Order ID' in line:
                    header_index = i
                    break
            
            if header_index is None:
                raise ValueError("Could not find header row containing 'Order ID'")
            
            # Get the header and data lines
            header_line = lines[header_index]
            data_lines = lines[header_index + 1:]
            
            # Detect delimiter from header
            sniffer = csv.Sniffer()
            delimiter = sniffer.sniff(header_line).delimiter
            
            print(f"CSV delimiter detected: '{delimiter}'")
            
            # Create reader with just the header and data
            reader = csv.DictReader([header_line] + data_lines, delimiter=delimiter)
            
            print(f"CSV columns: {reader.fieldnames}")
            print()
            
            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                try:
                    # Map CSV columns to database fields
                    # Crypto.com export format: Order ID, Time (UTC), Pair, Order Type, Side, Order Amount, Average Price, Deal Volume, Total, Trigger Condition, Status
                    
                    order_id = row.get('Order ID') or row.get('order_id') or row.get('orderId')
                    instrument_name = row.get('Pair') or row.get('instrument_name') or row.get('Symbol') or row.get('symbol')
                    order_type = row.get('Order Type') or row.get('order_type') or row.get('Type') or row.get('type') or 'MARKET'
                    side = row.get('Side') or row.get('side') or row.get('direction') or 'BUY'
                    status = row.get('Status') or row.get('status') or 'FILLED'
                    
                    # Parse quantities and prices
                    # Crypto.com CSV: Order Amount, Average Price, Deal Volume, Total
                    try:
                        quantity = float(row.get('Deal Volume', 0) or row.get('Order Amount', 0) or row.get('quantity', 0) or 0)
                        price = float(row.get('Average Price', 0) or row.get('price', 0) or row.get('Price', 0) or 0)
                        order_value = float(row.get('Total', 0) or row.get('order_value', 0) or quantity * price)
                    except (ValueError, TypeError):
                        print(f"Warning: Row {row_num} has invalid numeric values")
                        continue
                    
                    # Parse timestamps
                    # Crypto.com CSV: Time (UTC) format: 2025-10-24 14:40:43.634
                    try:
                        time_str = row.get('Time (UTC)') or row.get('create_time') or row.get('Timestamp') or row.get('Date')
                        if time_str:
                            # Parse Crypto.com format: 2025-10-24 14:40:43.634
                            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S.%f')
                            create_time = int(dt.timestamp() * 1000)
                        else:
                            create_time = int(datetime.now().timestamp() * 1000)
                    except Exception as e:
                        print(f"Warning: Could not parse timestamp for row {row_num}: {time_str if 'time_str' in locals() else 'N/A'}")
                        create_time = int(datetime.now().timestamp() * 1000)
                    
                    # Prepare raw data
                    raw_data = json.dumps(row)
                    
                    # Insert into database (INSERT OR REPLACE preserves existing data)
                    # This ensures that:
                    # 1. Old CSV data is never deleted
                    # 2. New orders are added
                    # 3. Existing orders (by order_id) are updated if CSV has newer data
                    cursor.execute("""
                        INSERT OR REPLACE INTO order_history 
                        (order_id, client_oid, instrument_name, order_type, side, status,
                         quantity, price, order_value, create_time, update_time, raw_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        str(order_id),
                        row.get('client_oid') or row.get('client_order_id'),
                        instrument_name,
                        order_type,
                        side,
                        status,
                        quantity,
                        price,
                        order_value,
                        create_time,
                        create_time,
                        raw_data
                    ))
                    
                    imported_count += 1
                    
                except Exception as e:
                    print(f"Error importing row {row_num}: {e}")
                    print(f"  Row data: {row}")
                    error_count += 1
                    continue
        
        conn.commit()
        print(f"\n✅ Import complete!")
        print(f"   Imported: {imported_count} orders")
        print(f"   Errors: {error_count}")
        
    except FileNotFoundError:
        print(f"❌ Error: CSV file not found: {csv_file_path}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python import_orders.py <csv_file_path>")
        print("\nExample:")
        print("  python import_orders.py orders.csv")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    parse_csv_and_import(csv_file)
