#!/usr/bin/env python3
"""
One-off script to create the signal_throttle_states table if it doesn't exist.
This table is required for BuyIndexMonitorService and SignalMonitorService throttling.
"""
import sys
import os
import logging

# Add parent directory to sys.path to allow importing app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text, inspect
from app.database import engine, Base
from app.models.signal_throttle import SignalThrottleState

# Configure basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_signal_throttle_table():
    """Create signal_throttle_states table if it doesn't exist."""
    if engine is None:
        logger.error("Database engine is None - cannot create table")
        return False
    
    try:
        # Check if table already exists
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        if "signal_throttle_states" in existing_tables:
            logger.info("✅ Table 'signal_throttle_states' already exists")
            return True
        
        logger.info("Creating table 'signal_throttle_states'...")
        
        # Import the model to ensure it's registered with Base
        # This will make Base.metadata aware of the table
        from app.models.signal_throttle import SignalThrottleState
        
        # Create all tables (this will only create missing ones)
        Base.metadata.create_all(bind=engine, tables=[SignalThrottleState.__table__])
        
        logger.info("✅ Table 'signal_throttle_states' created successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error creating signal_throttle_states table: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = create_signal_throttle_table()
    sys.exit(0 if success else 1)












