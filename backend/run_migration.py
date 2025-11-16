#!/usr/bin/env python3
"""Run database migration to create portfolio_loans table"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, Base
from app.models.portfolio_loan import PortfolioLoan

def main():
    """Create portfolio_loans table"""
    try:
        print("Creating portfolio_loans table...")
        Base.metadata.create_all(bind=engine, tables=[PortfolioLoan.__table__])
        print("✅ Portfolio loans table created successfully!")
        return 0
    except Exception as e:
        print(f"❌ Error creating table: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

