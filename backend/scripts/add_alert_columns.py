#!/usr/bin/env python3
"""Add sell_alert_enabled and buy_alert_enabled columns to watchlist_items if they don't exist"""
import sys
import os
sys.path.insert(0, '/app')

from app.database import SessionLocal, engine
from sqlalchemy import text

db = SessionLocal()
try:
    # Check if columns exist
    result = db.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'watchlist_items' 
        AND column_name IN ('sell_alert_enabled', 'buy_alert_enabled')
    """))
    existing = [row[0] for row in result]
    print(f"Existing columns: {existing}")
    
    # Add missing columns
    if "sell_alert_enabled" not in existing:
        db.execute(text("ALTER TABLE watchlist_items ADD COLUMN sell_alert_enabled BOOLEAN DEFAULT FALSE"))
        print("✅ Added sell_alert_enabled column")
    if "buy_alert_enabled" not in existing:
        db.execute(text("ALTER TABLE watchlist_items ADD COLUMN buy_alert_enabled BOOLEAN DEFAULT FALSE"))
        print("✅ Added buy_alert_enabled column")
    
    db.commit()
    print("✅ Migration complete")
finally:
    db.close()


