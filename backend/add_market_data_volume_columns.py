#!/usr/bin/env python3
"""
Migration script to add current_volume, avg_volume, and volume_ratio columns to market_data table
"""
import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine

def add_columns():
    """Add current_volume, avg_volume, and volume_ratio columns to market_data table"""
    db_path = engine.url.database
    
    print(f"Connecting to database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(market_data)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # Add current_volume column if it doesn't exist
        if 'current_volume' not in columns:
            print("Adding current_volume column...")
            cursor.execute("""
                ALTER TABLE market_data 
                ADD COLUMN current_volume REAL
            """)
            print("✅ Added current_volume column")
        else:
            print("ℹ️  current_volume column already exists")
        
        # Add avg_volume column if it doesn't exist
        if 'avg_volume' not in columns:
            print("Adding avg_volume column...")
            cursor.execute("""
                ALTER TABLE market_data 
                ADD COLUMN avg_volume REAL
            """)
            print("✅ Added avg_volume column")
        else:
            print("ℹ️  avg_volume column already exists")
        
        # Add volume_ratio column if it doesn't exist
        if 'volume_ratio' not in columns:
            print("Adding volume_ratio column...")
            cursor.execute("""
                ALTER TABLE market_data 
                ADD COLUMN volume_ratio REAL
            """)
            print("✅ Added volume_ratio column")
        else:
            print("ℹ️  volume_ratio column already exists")
        
        conn.commit()
        print("\n✅ Migration completed successfully!")
        
        # Verify columns
        cursor.execute("PRAGMA table_info(market_data)")
        columns_after = [row[1] for row in cursor.fetchall()]
        print(f"\nColumns in market_data: {', '.join(columns_after)}")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error during migration: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    add_columns()

