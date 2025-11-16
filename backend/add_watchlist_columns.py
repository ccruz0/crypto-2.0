#!/usr/bin/env python3
"""
Migration script to add is_deleted and alert_enabled columns to watchlist_items table
"""
import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine

def add_columns():
    """Add is_deleted and alert_enabled columns to watchlist_items table"""
    db_path = engine.url.database
    
    print(f"Connecting to database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(watchlist_items)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # Add is_deleted column if it doesn't exist
        if 'is_deleted' not in columns:
            print("Adding is_deleted column...")
            cursor.execute("""
                ALTER TABLE watchlist_items 
                ADD COLUMN is_deleted BOOLEAN DEFAULT 0 NOT NULL
            """)
            print("✅ Added is_deleted column")
        else:
            print("ℹ️  is_deleted column already exists")
        
        # Add alert_enabled column if it doesn't exist
        if 'alert_enabled' not in columns:
            print("Adding alert_enabled column...")
            cursor.execute("""
                ALTER TABLE watchlist_items 
                ADD COLUMN alert_enabled BOOLEAN DEFAULT 0 NOT NULL
            """)
            print("✅ Added alert_enabled column")
        else:
            print("ℹ️  alert_enabled column already exists")
        
        # Add skip_sl_tp_reminder column if it doesn't exist (from model)
        if 'skip_sl_tp_reminder' not in columns:
            print("Adding skip_sl_tp_reminder column...")
            cursor.execute("""
                ALTER TABLE watchlist_items 
                ADD COLUMN skip_sl_tp_reminder BOOLEAN DEFAULT 0 NOT NULL
            """)
            print("✅ Added skip_sl_tp_reminder column")
        else:
            print("ℹ️  skip_sl_tp_reminder column already exists")
        
        conn.commit()
        print("\n✅ Migration completed successfully!")
        
        # Verify columns
        cursor.execute("PRAGMA table_info(watchlist_items)")
        columns_after = [row[1] for row in cursor.fetchall()]
        print(f"\nColumns in watchlist_items: {', '.join(columns_after)}")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error during migration: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    add_columns()

