"""Script to create database tables for new models"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, Base
from app.models.trade_signal import TradeSignal
from app.models.exchange_balance import ExchangeBalance
from app.models.exchange_order import ExchangeOrder

def create_tables():
    """Create all database tables"""
    try:
        print("Creating database tables...")
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        
        print("✅ Tables created successfully!")
        print("\nCreated tables:")
        print("  - trade_signals")
        print("  - exchange_balances")
        print("  - exchange_orders")
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        raise

if __name__ == "__main__":
    create_tables()

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, Base
from app.models.trade_signal import TradeSignal
from app.models.exchange_balance import ExchangeBalance
from app.models.exchange_order import ExchangeOrder

def create_tables():
    """Create all database tables"""
    try:
        print("Creating database tables...")
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        
        print("✅ Tables created successfully!")
        print("\nCreated tables:")
        print("  - trade_signals")
        print("  - exchange_balances")
        print("  - exchange_orders")
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        raise

if __name__ == "__main__":
    create_tables()

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, Base
from app.models.trade_signal import TradeSignal
from app.models.exchange_balance import ExchangeBalance
from app.models.exchange_order import ExchangeOrder

def create_tables():
    """Create all database tables"""
    try:
        print("Creating database tables...")
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        
        print("✅ Tables created successfully!")
        print("\nCreated tables:")
        print("  - trade_signals")
        print("  - exchange_balances")
        print("  - exchange_orders")
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        raise

if __name__ == "__main__":
    create_tables()

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, Base
from app.models.trade_signal import TradeSignal
from app.models.exchange_balance import ExchangeBalance
from app.models.exchange_order import ExchangeOrder

def create_tables():
    """Create all database tables"""
    try:
        print("Creating database tables...")
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        
        print("✅ Tables created successfully!")
        print("\nCreated tables:")
        print("  - trade_signals")
        print("  - exchange_balances")
        print("  - exchange_orders")
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        raise

if __name__ == "__main__":
    create_tables()

