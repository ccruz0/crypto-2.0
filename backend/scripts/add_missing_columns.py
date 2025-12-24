#!/usr/bin/env python3
"""
Migration script to add remaining missing columns to watchlist_items table
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine
from sqlalchemy import text, inspect

def add_missing_columns():
    """Add missing columns to watchlist_items table"""
    db = SessionLocal()
    try:
        # Check which columns exist
        inspector = inspect(engine)
        columns = inspector.get_columns('watchlist_items')
        existing_columns = [col['name'] for col in columns]
        
        print(f"📊 Existing columns: {len(existing_columns)}")
        
        columns_to_add = []
        
        # Check min_price_change_pct
        if 'min_price_change_pct' not in existing_columns:
            columns_to_add.append(('min_price_change_pct', 'FLOAT'))
        else:
            print("✅ Column min_price_change_pct already exists")
        
        # Check alert_cooldown_minutes
        if 'alert_cooldown_minutes' not in existing_columns:
            columns_to_add.append(('alert_cooldown_minutes', 'FLOAT'))
        else:
            print("✅ Column alert_cooldown_minutes already exists")
        
        # Check skip_sl_tp_reminder
        if 'skip_sl_tp_reminder' not in existing_columns:
            columns_to_add.append(('skip_sl_tp_reminder', 'BOOLEAN NOT NULL DEFAULT FALSE'))
        else:
            print("✅ Column skip_sl_tp_reminder already exists")
        
        if not columns_to_add:
            print("✅ All missing columns already exist - no migration needed")
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
        
        # Verify
        print("\n📊 Verification:")
        inspector = inspect(engine)
        columns = inspector.get_columns('watchlist_items')
        final_columns = [col['name'] for col in columns]
        print(f"   - Total columns: {len(final_columns)}")
        print(f"   - min_price_change_pct: {'✅' if 'min_price_change_pct' in final_columns else '❌'}")
        print(f"   - alert_cooldown_minutes: {'✅' if 'alert_cooldown_minutes' in final_columns else '❌'}")
        print(f"   - skip_sl_tp_reminder: {'✅' if 'skip_sl_tp_reminder' in final_columns else '❌'}")
        
        print("\n✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    add_missing_columns()

