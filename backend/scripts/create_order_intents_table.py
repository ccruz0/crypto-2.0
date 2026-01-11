#!/usr/bin/env python3
"""
Create order_intents table migration script.

This script creates the order_intents table for atomic deduplication of order intents.
Run this once to add the table to your database.
"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import text
from app.database import engine, Base
from app.models.order_intent import OrderIntent

def create_order_intents_table():
    """Create order_intents table if it doesn't exist"""
    if engine is None:
        print("❌ Database engine is not available")
        return False
    
    try:
        # Create all tables (SQLAlchemy will skip if they already exist)
        Base.metadata.create_all(bind=engine, tables=[OrderIntent.__table__])
        print("✅ order_intents table created successfully")
        return True
    except Exception as e:
        print(f"❌ Error creating order_intents table: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Creating order_intents table...")
    success = create_order_intents_table()
    sys.exit(0 if success else 1)
