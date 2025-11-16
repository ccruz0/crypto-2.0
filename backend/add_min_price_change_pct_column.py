#!/usr/bin/env python3
"""
Migration script to add min_price_change_pct column to watchlist_items table
This column stores the minimum price change percentage required for order creation/alerts
Default value: 3.0 (if not set)
"""
import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine

def is_postgresql():
    """Check if database is PostgreSQL"""
    return 'postgresql' in str(engine.url).lower() or 'postgres' in str(engine.url).lower()

def add_column_sqlite():
    """Add min_price_change_pct column to watchlist_items table (SQLite)"""
    db_path = engine.url.database
    
    print(f"Connecting to SQLite database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(watchlist_items)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'min_price_change_pct' not in columns:
            print("Adding min_price_change_pct column...")
            cursor.execute("""
                ALTER TABLE watchlist_items 
                ADD COLUMN min_price_change_pct REAL
            """)
            print("✅ Added min_price_change_pct column")
        else:
            print("ℹ️  min_price_change_pct column already exists")
        
        conn.commit()
        print("\n✅ Migration completed successfully!")
        
        # Verify column
        cursor.execute("PRAGMA table_info(watchlist_items)")
        columns_after = [row[1] for row in cursor.fetchall()]
        print(f"\nColumns in watchlist_items: {', '.join(columns_after)}")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error during migration: {e}")
        raise
    finally:
        conn.close()

def add_column_postgresql():
    """Add min_price_change_pct column to watchlist_items table (PostgreSQL)"""
    from sqlalchemy import text
    
    print(f"Connecting to PostgreSQL database: {engine.url}")
    
    with engine.connect() as conn:
        try:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'watchlist_items' 
                AND column_name = 'min_price_change_pct'
            """))
            
            if result.fetchone():
                print("ℹ️  min_price_change_pct column already exists")
            else:
                print("Adding min_price_change_pct column...")
                conn.execute(text("""
                    ALTER TABLE watchlist_items 
                    ADD COLUMN min_price_change_pct FLOAT
                """))
                conn.commit()
                print("✅ Added min_price_change_pct column")
            
            print("\n✅ Migration completed successfully!")
            
            # Verify column
            result = conn.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'watchlist_items' 
                AND column_name = 'min_price_change_pct'
            """))
            row = result.fetchone()
            if row:
                print(f"\nColumn verified: {row[0]} ({row[1]})")
            
        except Exception as e:
            conn.rollback()
            print(f"❌ Error during migration: {e}")
            raise

def main():
    """Main migration function"""
    try:
        if is_postgresql():
            print("Detected PostgreSQL database")
            add_column_postgresql()
        else:
            print("Detected SQLite database")
            add_column_sqlite()
        return 0
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

