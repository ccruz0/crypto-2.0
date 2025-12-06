#!/usr/bin/env python3
"""
Migration script to add is_deleted column to watchlist_items table
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine
from sqlalchemy import text

def add_is_deleted_column():
    """Add is_deleted column to watchlist_items table if it doesn't exist"""
    db = SessionLocal()
    try:
        # Check if column exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='watchlist_items' AND column_name='is_deleted'
        """))
        exists = result.fetchone() is not None
        
        if exists:
            print("✅ Column is_deleted already exists")
        else:
            print("📝 Adding is_deleted column to watchlist_items table...")
            # Add column with default value
            db.execute(text("ALTER TABLE watchlist_items ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT FALSE"))
            db.commit()
            print("✅ Column is_deleted added successfully")
        
        # Verify
        result = db.execute(text("SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE is_deleted = TRUE) as deleted, COUNT(*) FILTER (WHERE is_deleted = FALSE) as active FROM watchlist_items"))
        row = result.fetchone()
        print(f"📊 Watchlist stats: Total={row[0]}, Deleted={row[1]}, Active={row[2]}")
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    add_is_deleted_column()

