#!/usr/bin/env python3
"""
Migration script to add current_volume column to market_data table
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine
from sqlalchemy import text, inspect

def add_market_data_columns():
    """Add missing columns to market_data table"""
    db = SessionLocal()
    try:
        # Check which columns exist
        inspector = inspect(engine)
        columns = inspector.get_columns('market_data')
        existing_columns = [col['name'] for col in columns]
        
        print(f"📊 Existing columns in market_data: {len(existing_columns)}")
        
        columns_to_add = []
        
        # Check current_volume
        if 'current_volume' not in existing_columns:
            columns_to_add.append(('current_volume', 'FLOAT'))
        else:
            print("✅ Column current_volume already exists")
        
        if not columns_to_add:
            print("✅ All columns already exist - no migration needed")
            return
        
        # Add missing columns
        print(f"\n📝 Adding {len(columns_to_add)} missing column(s)...")
        for col_name, col_def in columns_to_add:
            print(f"   - Adding {col_name}...")
            try:
                db.execute(text(f"ALTER TABLE market_data ADD COLUMN {col_name} {col_def}"))
                db.commit()
                print(f"   ✅ Column {col_name} added successfully")
            except Exception as e:
                db.rollback()
                print(f"   ❌ Error adding {col_name}: {e}")
                raise
        
        # Verify
        print("\n📊 Verification:")
        inspector = inspect(engine)
        columns = inspector.get_columns('market_data')
        final_columns = [col['name'] for col in columns]
        print(f"   - Total columns: {len(final_columns)}")
        print(f"   - current_volume: {'✅' if 'current_volume' in final_columns else '❌'}")
        
        print("\n✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    add_market_data_columns()













