#!/usr/bin/env python3
"""
Diagnostic script to check MarketData status and identify why RSI/Volume show defaults
"""
import sys
import os
from datetime import datetime, timezone

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

try:
    from app.database import SessionLocal
    from app.models.market_price import MarketData
    from sqlalchemy import func
    
    db = SessionLocal()
    
    print("=" * 80)
    print("MarketData Diagnostic Report")
    print("=" * 80)
    print()
    
    # Get all MarketData records
    all_market_data = db.query(MarketData).order_by(MarketData.updated_at.desc()).limit(20).all()
    
    if not all_market_data:
        print("❌ No MarketData records found in database!")
        print("   This means the market_updater process may not be running.")
        db.close()
        sys.exit(1)
    
    print(f"Found {len(all_market_data)} MarketData records (showing most recent 20):")
    print()
    
    # Count records with default values
    rsi_default_count = 0
    volume_zero_count = 0
    stale_count = 0
    
    now = datetime.now(timezone.utc)
    
    for md in all_market_data:
        # Check if RSI is default (50.0)
        is_rsi_default = md.rsi is not None and abs(md.rsi - 50.0) < 0.01
        
        # Check if volume_ratio is zero
        is_volume_zero = md.volume_ratio is None or md.volume_ratio == 0.0
        
        # Check if stale (older than 5 minutes)
        is_stale = False
        if md.updated_at:
            if md.updated_at.tzinfo is None:
                updated_at = md.updated_at.replace(tzinfo=timezone.utc)
            else:
                updated_at = md.updated_at
            age_seconds = (now - updated_at).total_seconds()
            is_stale = age_seconds > 300  # 5 minutes
        
        if is_rsi_default:
            rsi_default_count += 1
        if is_volume_zero:
            volume_zero_count += 1
        if is_stale:
            stale_count += 1
        
        # Show details for first 5 records
        if all_market_data.index(md) < 5:
            age_str = "STALE" if is_stale else "FRESH"
            rsi_str = f"{md.rsi:.2f}" if md.rsi is not None else "NULL"
            vol_str = f"{md.volume_ratio:.2f}x" if md.volume_ratio is not None else "NULL"
            
            print(f"  {md.symbol:12} | RSI: {rsi_str:6} | Vol: {vol_str:8} | Updated: {md.updated_at} ({age_str})")
    
    print()
    print("=" * 80)
    print("Summary:")
    print(f"  • Records with RSI=50 (default): {rsi_default_count}/{len(all_market_data)}")
    print(f"  • Records with Volume=0: {volume_zero_count}/{len(all_market_data)}")
    print(f"  • Stale records (>5min old): {stale_count}/{len(all_market_data)}")
    print()
    
    if rsi_default_count == len(all_market_data):
        print("⚠️  ALL records have default RSI=50!")
        print("   This suggests:")
        print("   1. Market updater is not fetching OHLCV data successfully")
        print("   2. OHLCV fetches are returning < 50 candles (insufficient data)")
        print("   3. Market updater process may not be running")
    elif rsi_default_count > len(all_market_data) * 0.5:
        print("⚠️  Most records have default RSI=50")
        print("   This suggests OHLCV data fetching is partially failing")
    
    if volume_zero_count == len(all_market_data):
        print("⚠️  ALL records have Volume=0!")
        print("   This suggests volume calculation is failing")
    elif volume_zero_count > len(all_market_data) * 0.5:
        print("⚠️  Most records have Volume=0")
        print("   This suggests volume calculation is partially failing")
    
    if stale_count == len(all_market_data):
        print("⚠️  ALL records are STALE (>5min old)!")
        print("   This suggests the market_updater process is NOT running")
    elif stale_count > len(all_market_data) * 0.5:
        print("⚠️  Most records are STALE")
        print("   This suggests the market_updater process is running slowly or intermittently")
    
    # Check most recent update time
    most_recent = max((md.updated_at for md in all_market_data if md.updated_at), default=None)
    if most_recent:
        if most_recent.tzinfo is None:
            most_recent = most_recent.replace(tzinfo=timezone.utc)
        age_seconds = (now - most_recent).total_seconds()
        print()
        print(f"Most recent update: {most_recent} ({age_seconds:.0f} seconds ago)")
        if age_seconds > 300:
            print("⚠️  Market updater appears to be NOT running or stuck")
        elif age_seconds > 120:
            print("⚠️  Market updater is running slowly")
        else:
            print("✅ Market updater appears to be running normally")
    
    db.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)




