#!/usr/bin/env python3
"""Add alert_cooldown_minutes column to watchlist_items"""
from app.database import engine
from sqlalchemy import text

with engine.begin() as conn:
    # Check if column exists
    result = conn.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'watchlist_items' 
        AND column_name = 'alert_cooldown_minutes'
    """))
    if result.fetchone():
        print("✅ Column already exists")
    else:
        print("Adding column...")
        conn.execute(text("""
            ALTER TABLE watchlist_items 
            ADD COLUMN alert_cooldown_minutes FLOAT
        """))
        print("✅ Column added successfully!")





