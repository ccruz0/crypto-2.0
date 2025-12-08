#!/usr/bin/env python3
"""
Migration script to add order_skipped column to telegram_messages table.

This script is idempotent - safe to run multiple times.
It checks if the column exists before adding it.

Usage:
    python scripts/migrate_add_order_skipped.py
    Or from Docker:
    docker compose exec backend python scripts/migrate_add_order_skipped.py
"""
import sys
import os
import logging

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text, inspect
from app.database import engine

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    if engine is None:
        logger.error("Database engine is None - cannot check column")
        return False
    
    try:
        inspector = inspect(engine)
        columns = inspector.get_columns(table_name)
        return any(col.get("name") == column_name for col in columns)
    except Exception as e:
        logger.warning(f"Error checking column existence: {e}")
        return False


def run_migration():
    """Run the migration to add order_skipped column."""
    if engine is None:
        logger.error("❌ Database engine is None - cannot run migration")
        return False
    
    try:
        with engine.connect() as conn:
            # First, ensure the table exists (create if it doesn't)
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            
            if "telegram_messages" not in tables:
                logger.info("Table telegram_messages does not exist. Creating it first...")
                # Create table with all columns including order_skipped
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS telegram_messages (
                        id SERIAL PRIMARY KEY,
                        message TEXT NOT NULL,
                        symbol VARCHAR(50),
                        blocked BOOLEAN NOT NULL DEFAULT FALSE,
                        order_skipped BOOLEAN NOT NULL DEFAULT FALSE,
                        throttle_status VARCHAR(20),
                        throttle_reason TEXT,
                        timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """))
                # Create indexes with IF NOT EXISTS
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_timestamp ON telegram_messages (timestamp)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_symbol ON telegram_messages (symbol)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_blocked ON telegram_messages (blocked)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_order_skipped ON telegram_messages (order_skipped)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_symbol_blocked ON telegram_messages (symbol, blocked)"))
                conn.commit()
                logger.info("✅ Created telegram_messages table with all columns including order_skipped")
                return True
            
            # Check if column already exists
            if column_exists("telegram_messages", "order_skipped"):
                logger.info("ℹ️  Column order_skipped already exists in telegram_messages table")
                logger.info("✅ Migration already applied - skipping")
                return True
            
            logger.info("Adding order_skipped column to telegram_messages table...")
            
            # Add column
            conn.execute(text("""
                ALTER TABLE telegram_messages 
                ADD COLUMN order_skipped BOOLEAN NOT NULL DEFAULT FALSE
            """))
            
            logger.info("✅ Added order_skipped column")
            
            # Create index
            logger.info("Creating index on order_skipped column...")
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_telegram_messages_order_skipped 
                ON telegram_messages(order_skipped)
            """))
            
            logger.info("✅ Created index ix_telegram_messages_order_skipped")
            
            # Commit the transaction
            conn.commit()
            
            # Verify
            result = conn.execute(text("""
                SELECT 
                    column_name, 
                    data_type, 
                    is_nullable,
                    column_default
                FROM information_schema.columns 
                WHERE table_name = 'telegram_messages' 
                AND column_name = 'order_skipped'
            """))
            
            row = result.fetchone()
            if row:
                logger.info(f"✅ Verification: column={row[0]}, type={row[1]}, nullable={row[2]}, default={row[3]}")
            
            # Show sample of existing rows
            result = conn.execute(text("""
                SELECT 
                    id, 
                    symbol, 
                    blocked, 
                    order_skipped, 
                    LEFT(message, 80) as message_preview,
                    timestamp
                FROM telegram_messages 
                ORDER BY timestamp DESC 
                LIMIT 5
            """))
            
            rows = result.fetchall()
            if rows:
                logger.info(f"\n📊 Sample of existing rows (all should have order_skipped=false):")
                for row in rows:
                    logger.info(f"  ID={row[0]}, symbol={row[1]}, blocked={row[2]}, order_skipped={row[3]}, message={row[4][:60]}...")
            
            logger.info("\n✅ Migration completed successfully!")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error running migration: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
