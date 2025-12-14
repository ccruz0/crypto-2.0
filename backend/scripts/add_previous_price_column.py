#!/usr/bin/env python3
"""
Script to add previous_price column to signal_throttle_states table.
This column stores the previous price before updating last_price, enabling
price change percentage calculation in the monitoring dashboard.
"""
import sys
import os
import logging

# Add parent directory to sys.path to allow importing app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text, inspect
from app.database import engine

# Configure basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def add_previous_price_column():
    """Add previous_price column to signal_throttle_states table if it doesn't exist."""
    if engine is None:
        logger.error("Database engine is None - cannot add column")
        return False
    
    try:
        # Check if column already exists
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('signal_throttle_states')]
        
        if 'previous_price' in columns:
            logger.info("✅ Column 'previous_price' already exists in signal_throttle_states")
            return True
        
        logger.info("Adding column 'previous_price' to signal_throttle_states...")
        
        with engine.begin() as conn:
            conn.execute(text("""
                ALTER TABLE signal_throttle_states 
                ADD COLUMN previous_price DOUBLE PRECISION NULL
            """))
        
        logger.info("✅ Column 'previous_price' added successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error adding previous_price column: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = add_previous_price_column()
    sys.exit(0 if success else 1)

