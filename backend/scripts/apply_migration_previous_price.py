#!/usr/bin/env python3
"""
Apply migration to add previous_price column to signal_throttle_states table.
This fixes the duplicate alert issue.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine, get_db

def apply_migration():
    """Apply the migration to add previous_price column"""
    migration_sql = """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 
            FROM information_schema.columns 
            WHERE table_name = 'signal_throttle_states' 
            AND column_name = 'previous_price'
        ) THEN
            ALTER TABLE signal_throttle_states 
            ADD COLUMN previous_price DOUBLE PRECISION NULL;
            
            RAISE NOTICE 'Column previous_price added to signal_throttle_states';
        ELSE
            RAISE NOTICE 'Column previous_price already exists in signal_throttle_states';
        END IF;
    END $$;
    """
    
    try:
        print("🔄 Applying migration: Add previous_price column to signal_throttle_states...")
        
        with engine.connect() as conn:
            result = conn.execute(text(migration_sql))
            conn.commit()
            print("✅ Migration applied successfully!")
            print("   The previous_price column has been added to signal_throttle_states table.")
            print("   This will fix the duplicate alert issue.")
            return True
            
    except Exception as e:
        print(f"❌ Error applying migration: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = apply_migration()
    sys.exit(0 if success else 1)






