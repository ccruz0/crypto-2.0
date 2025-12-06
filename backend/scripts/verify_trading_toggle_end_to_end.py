#!/usr/bin/env python3
"""End-to-end verification script for Trading toggle functionality.

This script verifies that:
1. The canonical row is correctly identified
2. Frontend updates match SignalMonitor reads
3. No duplicate rows cause inconsistencies

Usage:
    python -m backend.scripts.verify_trading_toggle_end_to_end [SYMBOL]
    
If SYMBOL is not provided, checks all symbols with trade_enabled=True.
"""
import sys
import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.watchlist_selector import get_canonical_watchlist_item, select_preferred_watchlist_item

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def verify_symbol(symbol: str, db: Session) -> Dict[str, Any]:
    """Verify a single symbol's trading toggle state."""
    symbol_upper = symbol.upper()
    result = {
        "symbol": symbol_upper,
        "status": "OK",
        "issues": [],
        "canonical_id": None,
        "canonical_trade_enabled": None,
        "duplicate_count": 0,
    }
    
    try:
        # Get all rows for this symbol
        all_rows = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol_upper
        ).all()
        
        if not all_rows:
            result["status"] = "NOT_FOUND"
            result["issues"].append(f"No watchlist items found for {symbol_upper}")
            return result
        
        result["duplicate_count"] = len(all_rows)
        
        # Get canonical row
        canonical = get_canonical_watchlist_item(db, symbol_upper)
        if not canonical:
            result["status"] = "ERROR"
            result["issues"].append(f"No canonical row found for {symbol_upper}")
            return result
        
        result["canonical_id"] = canonical.id
        result["canonical_trade_enabled"] = canonical.trade_enabled
        
        # Check for inconsistencies
        if len(all_rows) > 1:
            # Check if any duplicate has different trade_enabled
            for row in all_rows:
                if row.id != canonical.id and row.trade_enabled != canonical.trade_enabled:
                    result["status"] = "WARNING"
                    result["issues"].append(
                        f"Duplicate row id={row.id} has trade_enabled={row.trade_enabled} "
                        f"(canonical id={canonical.id} has trade_enabled={canonical.trade_enabled})"
                    )
        
        # Verify canonical selection logic
        preferred = select_preferred_watchlist_item(all_rows, symbol_upper)
        if preferred and preferred.id != canonical.id:
            result["status"] = "ERROR"
            result["issues"].append(
                f"Canonical selection mismatch: preferred id={preferred.id}, canonical id={canonical.id}"
            )
        
        # Check if trade_enabled=True but amount_usd is missing
        if canonical.trade_enabled and (not canonical.trade_amount_usd or canonical.trade_amount_usd <= 0):
            result["status"] = "WARNING"
            result["issues"].append(
                f"trade_enabled=True but trade_amount_usd={canonical.trade_amount_usd} "
                f"(orders will not be placed)"
            )
        
        return result
        
    except Exception as e:
        result["status"] = "ERROR"
        result["issues"].append(f"Exception: {e}")
        logger.error(f"Error verifying {symbol_upper}: {e}", exc_info=True)
        return result


def main():
    """Main verification function."""
    db: Session = SessionLocal()
    try:
        symbols_to_check: List[str] = []
        
        if len(sys.argv) > 1:
            symbols_to_check = [sys.argv[1].upper()]
        else:
            # Get all symbols with trade_enabled=True
            items = db.query(WatchlistItem).filter(
                WatchlistItem.trade_enabled == True
            ).all()
            symbols_seen = set()
            for item in items:
                symbol = (item.symbol or "").upper()
                if symbol:
                    symbols_seen.add(symbol)
            symbols_to_check = sorted(symbols_seen)
            
            if not symbols_to_check:
                logger.info("No symbols with trade_enabled=True found. Checking all watchlist symbols...")
                all_items = db.query(WatchlistItem).all()
                symbols_seen = set()
                for item in all_items:
                    symbol = (item.symbol or "").upper()
                    if symbol:
                        symbols_seen.add(symbol)
                symbols_to_check = sorted(symbols_seen)
        
        if not symbols_to_check:
            logger.warning("No symbols to check")
            return
        
        logger.info(f"Verifying {len(symbols_to_check)} symbol(s)...\n")
        
        results = []
        for symbol in symbols_to_check:
            result = verify_symbol(symbol, db)
            results.append(result)
        
        # Print summary
        print("\n" + "="*80)
        print("VERIFICATION SUMMARY")
        print("="*80)
        
        ok_count = sum(1 for r in results if r["status"] == "OK")
        warning_count = sum(1 for r in results if r["status"] == "WARNING")
        error_count = sum(1 for r in results if r["status"] in ["ERROR", "NOT_FOUND"])
        
        print(f"\nTotal symbols checked: {len(results)}")
        print(f"✅ OK: {ok_count}")
        print(f"⚠️  WARNINGS: {warning_count}")
        print(f"❌ ERRORS: {error_count}")
        
        # Print details
        print("\n" + "-"*80)
        print("DETAILED RESULTS")
        print("-"*80)
        
        for result in results:
            status_icon = {
                "OK": "✅",
                "WARNING": "⚠️",
                "ERROR": "❌",
                "NOT_FOUND": "❓"
            }.get(result["status"], "❓")
            
            print(f"\n{status_icon} {result['symbol']} (status: {result['status']})")
            print(f"   Canonical ID: {result['canonical_id']}")
            print(f"   trade_enabled: {result['canonical_trade_enabled']}")
            print(f"   Duplicate rows: {result['duplicate_count']}")
            
            if result["issues"]:
                for issue in result["issues"]:
                    print(f"   ⚠️  {issue}")
        
        # Exit with error code if there are issues
        if error_count > 0:
            sys.exit(1)
        elif warning_count > 0:
            sys.exit(0)  # Warnings are non-fatal
        else:
            sys.exit(0)
            
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()






