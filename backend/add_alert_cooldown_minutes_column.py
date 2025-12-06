#!/usr/bin/env python3
"""Script to add alert_cooldown_minutes column to watchlist_items table"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine
from sqlalchemy import text

def is_postgresql():
    """Check if database is PostgreSQL"""
    return 'postgresql' in str(engine.url).lower() or 'postgres' in str(engine.url).lower()

def add_column_postgresql():
    """Add alert_cooldown_minutes column to watchlist_items table (PostgreSQL)"""
    print(f"Connecting to PostgreSQL database: {engine.url}")
    
    with engine.connect() as conn:
        try:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'watchlist_items' 
                AND column_name = 'alert_cooldown_minutes'
            """))
            
            if result.fetchone():
                print("ℹ️  alert_cooldown_minutes column already exists")
            else:
                print("Adding alert_cooldown_minutes column...")
                conn.execute(text("""
                    ALTER TABLE watchlist_items 
                    ADD COLUMN alert_cooldown_minutes FLOAT
                """))
                conn.commit()
                print("✅ Added alert_cooldown_minutes column")
            
            print("\n✅ Migration completed successfully!")
            
            # Verify column
            result = conn.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'watchlist_items' 
                AND column_name = 'alert_cooldown_minutes'
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
            print("❌ SQLite not supported for this migration")
            return 1
        return 0
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

