#!/usr/bin/env python3
"""
Script to create the telegram_messages table if it doesn't exist.
"""
import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text, inspect
from app.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_telegram_messages_table():
    """Create telegram_messages table if it doesn't exist."""
    if engine is None:
        logger.error("Database engine is None")
        return False
    
    try:
        with engine.connect() as conn:
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            
            if "telegram_messages" in tables:
                logger.info("✅ Table telegram_messages already exists")
                result = conn.execute(text("SELECT COUNT(*) FROM telegram_messages"))
                count = result.scalar()
                logger.info(f"Total messages: {count}")
                return True
            
            logger.info("Creating telegram_messages table...")
            
            # Create table
            conn.execute(text("""
                CREATE TABLE telegram_messages (
                    id SERIAL PRIMARY KEY,
                    message TEXT NOT NULL,
                    symbol VARCHAR(50),
                    blocked BOOLEAN NOT NULL DEFAULT FALSE,
                    throttle_status VARCHAR(20),
                    throttle_reason TEXT,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            
            # Create indexes
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_timestamp ON telegram_messages (timestamp)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_symbol ON telegram_messages (symbol)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_blocked ON telegram_messages (blocked)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_symbol_blocked ON telegram_messages (symbol, blocked)"))
            
            conn.commit()
            logger.info("✅ Table telegram_messages created successfully")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error creating telegram_messages table: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = create_telegram_messages_table()
    sys.exit(0 if success else 1)


