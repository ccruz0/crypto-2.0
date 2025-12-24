#!/usr/bin/env python3
"""
Migration script to add alert_enabled, buy_alert_enabled, and sell_alert_enabled columns
to watchlist_items table
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine
from sqlalchemy import text, inspect

def add_alert_columns():
    """Add alert columns to watchlist_items table if they don't exist"""
    db = SessionLocal()
    try:
        # Check which columns exist
        inspector = inspect(engine)
        columns = inspector.get_columns('watchlist_items')
        existing_columns = [col['name'] for col in columns]
        
        print(f"📊 Existing columns: {sorted(existing_columns)}")
        
        columns_to_add = []
        
        # Check alert_enabled
        if 'alert_enabled' not in existing_columns:
            columns_to_add.append(('alert_enabled', 'BOOLEAN NOT NULL DEFAULT FALSE'))
        else:
            print("✅ Column alert_enabled already exists")
        
        # Check buy_alert_enabled
        if 'buy_alert_enabled' not in existing_columns:
            columns_to_add.append(('buy_alert_enabled', 'BOOLEAN NOT NULL DEFAULT FALSE'))
        else:
            print("✅ Column buy_alert_enabled already exists")
        
        # Check sell_alert_enabled
        if 'sell_alert_enabled' not in existing_columns:
            columns_to_add.append(('sell_alert_enabled', 'BOOLEAN NOT NULL DEFAULT FALSE'))
        else:
            print("✅ Column sell_alert_enabled already exists")
        
        if not columns_to_add:
            print("✅ All alert columns already exist - no migration needed")
            return
        
        # Add missing columns
        print(f"\n📝 Adding {len(columns_to_add)} missing column(s)...")
        for col_name, col_def in columns_to_add:
            print(f"   - Adding {col_name}...")
            try:
                db.execute(text(f"ALTER TABLE watchlist_items ADD COLUMN {col_name} {col_def}"))
                db.commit()
                print(f"   ✅ Column {col_name} added successfully")
            except Exception as e:
                db.rollback()
                print(f"   ❌ Error adding {col_name}: {e}")
                raise
        
        # Initialize values based on trade_enabled for existing rows
        # This ensures backward compatibility: if trade_enabled=True, set alert columns to True
        print("\n🔄 Initializing alert columns based on trade_enabled...")
        try:
            # Set alert_enabled = trade_enabled for existing rows
            db.execute(text("""
                UPDATE watchlist_items 
                SET alert_enabled = trade_enabled,
                    buy_alert_enabled = trade_enabled,
                    sell_alert_enabled = trade_enabled
                WHERE trade_enabled = 1
            """))
            db.commit()
            print("✅ Initialized alert columns for rows with trade_enabled=True")
        except Exception as e:
            db.rollback()
            print(f"⚠️  Warning: Could not initialize alert columns: {e}")
            # Don't fail the migration if initialization fails
        
        # Verify
        print("\n📊 Verification:")
        result = db.execute(text("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE alert_enabled = 1) as alert_enabled_count,
                COUNT(*) FILTER (WHERE buy_alert_enabled = 1) as buy_alert_enabled_count,
                COUNT(*) FILTER (WHERE sell_alert_enabled = 1) as sell_alert_enabled_count,
                COUNT(*) FILTER (WHERE trade_enabled = 1) as trade_enabled_count
            FROM watchlist_items
        """))
        row = result.fetchone()
        print(f"   - Total items: {row[0]}")
        print(f"   - alert_enabled=True: {row[1]}")
        print(f"   - buy_alert_enabled=True: {row[2]}")
        print(f"   - sell_alert_enabled=True: {row[3]}")
        print(f"   - trade_enabled=True: {row[4]}")
        
        print("\n✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    add_alert_columns()
