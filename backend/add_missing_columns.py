#!/usr/bin/env python3
"""Add missing columns to exchange_orders table"""
import sys
import os
import sqlite3

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine
from sqlalchemy import text

def add_missing_columns():
    """Add missing columns to exchange_orders table"""
    # Get database URL
    db_url = str(engine.url)
    
    if not db_url.startswith('sqlite'):
        print("This script is for SQLite databases only.")
        print(f"Current database: {db_url}")
        return False
    
    # Extract SQLite path
    sqlite_path = db_url.replace('sqlite:///', '')
    
    print(f"Connecting to SQLite database: {sqlite_path}")
    
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()
    
    try:
        # Check which columns exist
        cursor.execute("PRAGMA table_info(exchange_orders)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        print(f"Existing columns: {existing_columns}")
        
        # Add missing columns
        missing_columns = []
        
        if 'parent_order_id' not in existing_columns:
            print("Adding parent_order_id column...")
            cursor.execute("ALTER TABLE exchange_orders ADD COLUMN parent_order_id VARCHAR(100)")
            missing_columns.append('parent_order_id')
        
        if 'oco_group_id' not in existing_columns:
            print("Adding oco_group_id column...")
            cursor.execute("ALTER TABLE exchange_orders ADD COLUMN oco_group_id VARCHAR(100)")
            missing_columns.append('oco_group_id')
        
        if 'order_role' not in existing_columns:
            print("Adding order_role column...")
            cursor.execute("ALTER TABLE exchange_orders ADD COLUMN order_role VARCHAR(20)")
            missing_columns.append('order_role')
        
        if missing_columns:
            conn.commit()
            print(f"✅ Successfully added columns: {', '.join(missing_columns)}")
        else:
            print("✅ All columns already exist")
        
        # Create indexes if they don't exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_exchange_orders_%'")
        existing_indexes = [row[0] for row in cursor.fetchall()]
        
        if 'ix_exchange_orders_parent_order_id' not in existing_indexes:
            print("Creating index on parent_order_id...")
            cursor.execute("CREATE INDEX ix_exchange_orders_parent_order_id ON exchange_orders(parent_order_id)")
        
        if 'ix_exchange_orders_oco_group_id' not in existing_indexes:
            print("Creating index on oco_group_id...")
            cursor.execute("CREATE INDEX ix_exchange_orders_oco_group_id ON exchange_orders(oco_group_id)")
        
        conn.commit()
        print("✅ Database schema updated successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = add_missing_columns()
    sys.exit(0 if success else 1)

