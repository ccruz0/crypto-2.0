#!/usr/bin/env python3
"""
Diagnostic script to check why MarketData has default values instead of calculated ones
Checks database directly to see what's actually stored
"""
import sys
import os
from datetime import datetime, timezone, timedelta

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    from app.database import SessionLocal
    from app.models.market_price import MarketData
    from sqlalchemy import func, desc
    
    db = SessionLocal()
    
    print("=" * 80)
    print("MarketData Calculation Diagnostic")
    print("=" * 80)
    print()
    
    # Get all MarketData records
    all_market_data = db.query(MarketData).order_by(desc(MarketData.updated_at)).limit(50).all()
    
    if not all_market_data:
        print("❌ No MarketData records found!")
        db.close()
        sys.exit(1)
    
    now = datetime.now(timezone.utc)
    
    # Analyze records
    rsi_default_count = 0
    rsi_real_count = 0
    volume_zero_count = 0
    volume_real_count = 0
    stale_count = 0
    fresh_count = 0
    
    print(f"Analyzing {len(all_market_data)} most recent MarketData records:")
    print()
    print(f"{'Symbol':<15} | {'RSI':<8} | {'Vol Ratio':<10} | {'Updated':<20} | {'Status'}")
    print("-" * 80)
    
    for md in all_market_data[:20]:  # Show first 20
        # Check RSI
        is_rsi_default = md.rsi is not None and abs(md.rsi - 50.0) < 0.01
        if is_rsi_default:
            rsi_default_count += 1
        else:
            rsi_real_count += 1
        
        # Check volume
        is_volume_zero = md.volume_ratio is None or (md.volume_ratio is not None and abs(md.volume_ratio) < 0.01)
        if is_volume_zero:
            volume_zero_count += 1
        else:
            volume_real_count += 1
        
        # Check freshness
        if md.updated_at:
            if md.updated_at.tzinfo is None:
                updated_at = md.updated_at.replace(tzinfo=timezone.utc)
            else:
                updated_at = md.updated_at
            age_seconds = (now - updated_at).total_seconds()
            is_stale = age_seconds > 300  # 5 minutes
        else:
            is_stale = True
            age_seconds = None
        
        if is_stale:
            stale_count += 1
        else:
            fresh_count += 1
        
        # Format output
        rsi_str = f"{md.rsi:.2f}" if md.rsi is not None else "NULL"
        vol_str = f"{md.volume_ratio:.2f}x" if md.volume_ratio is not None else "NULL"
        age_str = f"{int(age_seconds)}s ago" if age_seconds is not None else "N/A"
        
        status = []
        if is_rsi_default:
            status.append("RSI=50")
        if is_volume_zero:
            status.append("Vol=0")
        if is_stale:
            status.append("STALE")
        status_str = ", ".join(status) if status else "OK"
        
        print(f"{md.symbol:<15} | {rsi_str:<8} | {vol_str:<10} | {age_str:<20} | {status_str}")
    
    print("-" * 80)
    print()
    
    # Summary
    print("=" * 80)
    print("Summary:")
    print(f"  Total records analyzed: {len(all_market_data)}")
    print(f"  RSI defaults (50.0): {rsi_default_count} ({rsi_default_count*100/len(all_market_data):.1f}%)")
    print(f"  RSI real values: {rsi_real_count} ({rsi_real_count*100/len(all_market_data):.1f}%)")
    print(f"  Volume zero: {volume_zero_count} ({volume_zero_count*100/len(all_market_data):.1f}%)")
    print(f"  Volume real values: {volume_real_count} ({volume_real_count*100/len(all_market_data):.1f}%)")
    print(f"  Stale records (>5min): {stale_count} ({stale_count*100/len(all_market_data):.1f}%)")
    print(f"  Fresh records (<5min): {fresh_count} ({fresh_count*100/len(all_market_data):.1f}%)")
    print()
    
    # Most recent update
    most_recent = max((md.updated_at for md in all_market_data if md.updated_at), default=None)
    if most_recent:
        if most_recent.tzinfo is None:
            most_recent = most_recent.replace(tzinfo=timezone.utc)
        age_seconds = (now - most_recent).total_seconds()
        print(f"Most recent update: {most_recent} ({age_seconds:.0f} seconds ago)")
        
        if age_seconds > 300:
            print("⚠️  Market updater appears to be NOT running or stuck")
            print("   Check: docker-compose --profile aws logs market-updater-aws")
        elif age_seconds > 120:
            print("⚠️  Market updater is running slowly")
        else:
            print("✅ Market updater appears to be running normally")
    
    # Find symbols with real values
    real_rsi_symbols = [md.symbol for md in all_market_data if md.rsi and abs(md.rsi - 50.0) > 1]
    if real_rsi_symbols:
        print()
        print(f"Symbols with real RSI values ({len(real_rsi_symbols)}):")
        for symbol in real_rsi_symbols[:10]:
            md = next((x for x in all_market_data if x.symbol == symbol), None)
            if md:
                print(f"  {symbol}: RSI={md.rsi:.2f}, Vol={md.volume_ratio:.2f}x" if md.volume_ratio else f"  {symbol}: RSI={md.rsi:.2f}, Vol=NULL")
    
    db.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

