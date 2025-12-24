#!/bin/bash
# Script para verificar el estado de MarketData y market_updater
# Ejecutar en el servidor AWS o localmente

set -e

echo "=========================================="
echo "MarketData Status Verification"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if we're on AWS server or local
if [ -f "/.dockerenv" ] || docker compose ps >/dev/null 2>&1; then
    IS_DOCKER=true
    echo "✓ Docker environment detected"
else
    IS_DOCKER=false
    echo "⚠ Local environment (no Docker)"
fi

echo ""
echo "1. Checking market_updater process status..."
echo "-------------------------------------------"

if [ "$IS_DOCKER" = true ]; then
    # Check if market-updater-aws container is running
    if docker compose ps market-updater-aws 2>/dev/null | grep -q "Up"; then
        echo -e "${GREEN}✓ market-updater-aws container is running${NC}"
        
        # Check recent logs
        echo ""
        echo "Recent market_updater logs (last 20 lines):"
        docker compose logs --tail=20 market-updater-aws 2>/dev/null | grep -i "update\|error\|warning" || echo "  (no relevant logs found)"
    else
        echo -e "${RED}✗ market-updater-aws container is NOT running${NC}"
        echo ""
        echo "Checking if it exists but is stopped:"
        docker compose ps market-updater-aws 2>/dev/null || echo "  Container not found in docker-compose"
    fi
    
    # Check backend-aws container logs for MarketData warnings
    echo ""
    echo "2. Checking backend logs for MarketData warnings..."
    echo "-------------------------------------------"
    WARNING_COUNT=$(docker compose logs backend-aws 2>/dev/null | grep -c "MarketData missing fields" || echo "0")
    if [ "$WARNING_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}⚠ Found $WARNING_COUNT warnings about missing MarketData fields${NC}"
        echo ""
        echo "Recent warnings (last 10):"
        docker compose logs backend-aws 2>/dev/null | grep "MarketData missing fields" | tail -10
    else
        echo -e "${GREEN}✓ No MarketData warnings found in backend logs${NC}"
    fi
else
    echo "⚠ Cannot check Docker containers (Docker not running or not available)"
    echo "  To check on AWS server, SSH in and run:"
    echo "  cd /home/ubuntu/automated-trading-platform"
    echo "  docker compose ps market-updater-aws"
fi

echo ""
echo "3. Checking MarketData in database..."
echo "-------------------------------------------"

if [ "$IS_DOCKER" = true ]; then
    # Try to query database through backend container
    echo "Querying MarketData table through backend container..."
    docker compose exec -T backend-aws python3 << 'PYTHON_SCRIPT' 2>/dev/null || echo "⚠ Could not query database"
import sys
import os
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.market_price import MarketData
from datetime import datetime, timedelta, timezone

db = SessionLocal()
try:
    # Get all MarketData entries
    all_market_data = db.query(MarketData).all()
    print(f"Total MarketData entries: {len(all_market_data)}")
    
    # Check for recent updates (last hour)
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_updates = db.query(MarketData).filter(MarketData.updated_at >= one_hour_ago).all()
    print(f"Entries updated in last hour: {len(recent_updates)}")
    
    # Check for stale data (> 2 hours old)
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    stale_data = db.query(MarketData).filter(MarketData.updated_at < two_hours_ago).all()
    if stale_data:
        print(f"\n⚠ Found {len(stale_data)} entries with data older than 2 hours:")
        for md in stale_data[:10]:  # Show first 10
            age_minutes = (datetime.now(timezone.utc) - md.updated_at.replace(tzinfo=timezone.utc)).total_seconds() / 60
            print(f"  - {md.symbol}: {age_minutes:.1f} minutes old")
        if len(stale_data) > 10:
            print(f"  ... and {len(stale_data) - 10} more")
    else:
        print("✓ All MarketData entries are recent (< 2 hours old)")
    
    # Sample some entries to show their status
    print("\nSample MarketData entries (first 5):")
    for md in all_market_data[:5]:
        has_rsi = "✓" if md.rsi is not None else "✗"
        has_ma50 = "✓" if md.ma50 is not None else "✗"
        has_ma200 = "✓" if md.ma200 is not None else "✗"
        has_ema10 = "✓" if md.ema10 is not None else "✗"
        age_minutes = (datetime.now(timezone.utc) - md.updated_at.replace(tzinfo=timezone.utc)).total_seconds() / 60 if md.updated_at else None
        age_str = f"{age_minutes:.1f}m ago" if age_minutes else "unknown"
        print(f"  {md.symbol}: price={md.price}, rsi={has_rsi}, ma50={has_ma50}, ma200={has_ma200}, ema10={has_ema10}, updated={age_str}")
        
finally:
    db.close()
PYTHON_SCRIPT

else
    echo "⚠ Cannot query database (Docker not available)"
    echo "  To check on AWS server, SSH in and run:"
    echo "  cd /home/ubuntu/automated-trading-platform"
    echo "  docker compose exec backend-aws python3 -c 'from app.database import SessionLocal; from app.models.market_price import MarketData; db = SessionLocal(); print(f\"Total: {db.query(MarketData).count()}\"); db.close()'"
fi

echo ""
echo "4. Checking watchlist symbols..."
echo "-------------------------------------------"

if [ "$IS_DOCKER" = true ]; then
    docker compose exec -T backend-aws python3 << 'PYTHON_SCRIPT' 2>/dev/null || echo "⚠ Could not query watchlist"
import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketData

db = SessionLocal()
try:
    # Get active watchlist items
    watchlist_items = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).all()
    print(f"Active watchlist items: {len(watchlist_items)}")
    
    # Check which symbols have MarketData
    symbols_with_data = []
    symbols_without_data = []
    
    for item in watchlist_items:
        md = db.query(MarketData).filter(MarketData.symbol == item.symbol.upper()).first()
        if md and md.price and md.price > 0:
            symbols_with_data.append(item.symbol)
        else:
            symbols_without_data.append(item.symbol)
    
    print(f"Symbols WITH MarketData: {len(symbols_with_data)}")
    print(f"Symbols WITHOUT MarketData: {len(symbols_without_data)}")
    
    if symbols_without_data:
        echo -e "${YELLOW}⚠ Missing MarketData for: ${symbols_without_data.join(', ')}${NC}"
    else:
        echo -e "${GREEN}✓ All watchlist symbols have MarketData${NC}"
        
finally:
    db.close()
PYTHON_SCRIPT
else
    echo "⚠ Cannot query watchlist (Docker not available)"
fi

echo ""
echo "=========================================="
echo "Verification complete"
echo "=========================================="

