#!/usr/bin/env python3
"""
Script to verify MarketData status and market_updater process
Can be run locally or on AWS server
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

try:
    from app.database import SessionLocal
    from app.models.market_price import MarketData
    from app.models.watchlist import WatchlistItem
    DB_AVAILABLE = True
except ImportError as e:
    print(f"⚠ Warning: Could not import database modules: {e}")
    print("  Make sure you're running from the correct directory")
    DB_AVAILABLE = False

def check_market_data_status():
    """Check MarketData status in database"""
    if not DB_AVAILABLE:
        print("❌ Cannot check MarketData: database modules not available")
        return
    
    print("=" * 60)
    print("MarketData Status Check")
    print("=" * 60)
    print()
    
    db = SessionLocal()
    try:
        # Get all MarketData entries
        all_market_data = db.query(MarketData).all()
        print(f"Total MarketData entries: {len(all_market_data)}")
        
        if len(all_market_data) == 0:
            print("⚠️  WARNING: No MarketData entries found in database!")
            print("   This means market_updater has not populated any data yet.")
            return
        
        # Check for recent updates (last hour)
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_updates = db.query(MarketData).filter(
            MarketData.updated_at >= one_hour_ago
        ).all()
        print(f"Entries updated in last hour: {len(recent_updates)}")
        
        # Check for stale data (> 2 hours old)
        two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
        stale_data = db.query(MarketData).filter(
            MarketData.updated_at < two_hours_ago
        ).all()
        
        if stale_data:
            print(f"\n⚠️  Found {len(stale_data)} entries with data older than 2 hours:")
            for md in stale_data[:10]:  # Show first 10
                if md.updated_at:
                    age_minutes = (datetime.now(timezone.utc) - md.updated_at.replace(tzinfo=timezone.utc)).total_seconds() / 60
                    print(f"  - {md.symbol}: {age_minutes:.1f} minutes old")
                else:
                    print(f"  - {md.symbol}: no updated_at timestamp")
            if len(stale_data) > 10:
                print(f"  ... and {len(stale_data) - 10} more")
        else:
            print("✓ All MarketData entries are recent (< 2 hours old)")
        
        # Sample some entries to show their status
        print("\nSample MarketData entries (first 10):")
        print("-" * 60)
        for md in all_market_data[:10]:
            has_rsi = "✓" if md.rsi is not None else "✗"
            has_ma50 = "✓" if md.ma50 is not None else "✗"
            has_ma200 = "✓" if md.ma200 is not None else "✗"
            has_ema10 = "✓" if md.ema10 is not None else "✗"
            has_atr = "✓" if md.atr is not None else "✗"
            
            if md.updated_at:
                age_minutes = (datetime.now(timezone.utc) - md.updated_at.replace(tzinfo=timezone.utc)).total_seconds() / 60
                age_str = f"{age_minutes:.1f}m ago"
            else:
                age_str = "unknown"
            
            print(f"{md.symbol:15} | price={md.price:>12.4f} | rsi={has_rsi} ma50={has_ma50} ma200={has_ma200} ema10={has_ema10} atr={has_atr} | updated={age_str}")
        
    finally:
        db.close()

def check_watchlist_coverage():
    """Check which watchlist symbols have MarketData"""
    if not DB_AVAILABLE:
        print("❌ Cannot check watchlist coverage: database modules not available")
        return
    
    print()
    print("=" * 60)
    print("Watchlist Coverage Check")
    print("=" * 60)
    print()
    
    db = SessionLocal()
    try:
        # Get active watchlist items
        watchlist_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        print(f"Active watchlist items: {len(watchlist_items)}")
        
        if len(watchlist_items) == 0:
            print("⚠️  No active watchlist items found")
            return
        
        # Check which symbols have MarketData
        symbols_with_data = []
        symbols_without_data = []
        symbols_with_incomplete_data = []
        
        for item in watchlist_items:
            symbol_upper = item.symbol.upper()
            md = db.query(MarketData).filter(
                MarketData.symbol == symbol_upper
            ).first()
            
            if md and md.price and md.price > 0:
                # Check if all indicators are present
                missing_indicators = []
                if md.rsi is None:
                    missing_indicators.append("rsi")
                if md.ma50 is None:
                    missing_indicators.append("ma50")
                if md.ma200 is None:
                    missing_indicators.append("ma200")
                if md.ema10 is None:
                    missing_indicators.append("ema10")
                if md.atr is None:
                    missing_indicators.append("atr")
                
                if missing_indicators:
                    symbols_with_incomplete_data.append((item.symbol, missing_indicators))
                else:
                    symbols_with_data.append(item.symbol)
            else:
                symbols_without_data.append(item.symbol)
        
        print(f"✓ Symbols WITH complete MarketData: {len(symbols_with_data)}")
        if symbols_with_data:
            print(f"  {', '.join(symbols_with_data[:10])}{'...' if len(symbols_with_data) > 10 else ''}")
        
        print(f"⚠️  Symbols WITH MarketData but missing indicators: {len(symbols_with_incomplete_data)}")
        if symbols_with_incomplete_data:
            for symbol, missing in symbols_with_incomplete_data:
                print(f"  - {symbol}: missing {', '.join(missing)}")
        
        print(f"❌ Symbols WITHOUT MarketData: {len(symbols_without_data)}")
        if symbols_without_data:
            print(f"  {', '.join(symbols_without_data)}")
            print()
            print("⚠️  These symbols will show '-' (None) values in the frontend")
            print("   Ensure market_updater is running to populate MarketData")
        else:
            print("  (none)")
        
    finally:
        db.close()

def main():
    """Main function"""
    print()
    print("MarketData Verification Script")
    print("=" * 60)
    print()
    
    if not DB_AVAILABLE:
        print("❌ Database modules not available")
        print("   Make sure you're running this from the project root or backend directory")
        print("   Or run it inside the Docker container:")
        print("   docker compose exec backend-aws python3 scripts/verify_market_data_status.py")
        return 1
    
    try:
        check_market_data_status()
        check_watchlist_coverage()
        
        print()
        print("=" * 60)
        print("Verification complete")
        print("=" * 60)
        print()
        print("Next steps:")
        print("1. If MarketData is missing or stale, check market_updater logs:")
        print("   docker compose logs market-updater-aws --tail=50")
        print()
        print("2. If market_updater is not running, start it:")
        print("   docker compose up -d market-updater-aws")
        print()
        print("3. Check backend logs for MarketData warnings:")
        print("   docker compose logs backend-aws | grep 'MarketData missing fields'")
        print()
        
        return 0
    except Exception as e:
        print(f"❌ Error during verification: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())











