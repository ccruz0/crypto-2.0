# Deploy and Verification Instructions

## ✅ Completed Tasks

### 1. Code Review ✅
- Reviewed and approved rollback changes in `routes_dashboard.py`
- Changes committed and pushed to repository

### 2. Script Fixes ✅
- Fixed `check_all_symbols.py` to handle missing `is_deleted` column gracefully

## 📋 Tasks to Complete

### Task 1: Deploy to AWS

**On AWS server, run:**

```bash
cd ~/automated-trading-platform

# Pull latest code
git pull origin main

# Rebuild and restart services
docker compose --profile aws build --no-cache backend-aws market-updater-aws
docker compose --profile aws up -d backend-aws market-updater-aws

# Wait for services to be healthy
sleep 15

# Check status
docker compose --profile aws ps backend-aws market-updater-aws
```

### Task 2: Verify Market Data

**On AWS server, run:**

```bash
cd ~/automated-trading-platform

# Check market data in database
docker compose --profile aws exec -T backend-aws python3 << 'PYTHON_SCRIPT'
from app.database import SessionLocal
from app.models.market_price import MarketData
from app.models.watchlist import WatchlistItem

db = SessionLocal()
try:
    # Count symbols with valid RSI
    md_count = db.query(MarketData).filter(MarketData.rsi.isnot(None)).count()
    total_md = db.query(MarketData).count()
    
    # Count watchlist items
    try:
        if hasattr(WatchlistItem, 'is_deleted'):
            watchlist_count = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).count()
        else:
            watchlist_count = db.query(WatchlistItem).count()
    except:
        watchlist_count = db.query(WatchlistItem).count()
    
    print(f"✅ MarketData entries: {total_md} total, {md_count} with RSI")
    print(f"✅ Watchlist items: {watchlist_count}")
    
    # Show sample of symbols with RSI
    sample = db.query(MarketData).filter(MarketData.rsi.isnot(None)).limit(10).all()
    print(f"\n📈 Sample symbols with RSI:")
    for md in sample:
        print(f"   {md.symbol}: RSI={md.rsi:.2f}, MA50={md.ma50:.2f if md.ma50 else 'None'}, Price={md.price:.4f if md.price else 'None'}")
finally:
    db.close()
PYTHON_SCRIPT
```

**Or use the check script:**

```bash
docker compose --profile aws exec -T backend-aws python3 backend/check_all_symbols.py | head -50
```

### Task 3: Verify Alerts Configuration

**On AWS server, run:**

```bash
cd ~/automated-trading-platform

# Check Telegram environment variables
docker compose --profile aws exec -T market-updater-aws env | grep -E "TELEGRAM|RUNTIME_ORIGIN|RUN_TELEGRAM"

# Check recent logs for market-updater
docker compose --profile aws logs --tail=50 market-updater-aws | grep -E "RSI|MarketData|ERROR|WARNING|TELEGRAM"

# Check recent logs for backend
docker compose --profile aws logs --tail=30 backend-aws | grep -E "ERROR|WARNING|alert"
```

### Task 4: Verify System Health

**On AWS server, run:**

```bash
cd ~/automated-trading-platform

# Check all services status
docker compose --profile aws ps

# Check service health
docker compose --profile aws exec backend-aws curl -f http://localhost:8002/ping_fast || echo "Health check failed"

# Check market-updater is running
docker compose --profile aws logs --tail=20 market-updater-aws | tail -20
```

## 🔍 What to Look For

### Market Data Verification:
- ✅ Most symbols should have RSI values (not None or 50.0 default)
- ✅ MA50 and EMA10 should be populated for most symbols
- ✅ Price should be current (not stale)
- ✅ Volume data should be present

### Alerts Verification:
- ✅ `RUNTIME_ORIGIN=AWS` in market-updater-aws environment
- ✅ `RUN_TELEGRAM=true` in market-updater-aws environment
- ✅ `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
- ✅ No errors in logs related to Telegram sending
- ✅ Market data updates are happening (check timestamps)

### System Health:
- ✅ All services are running (not restarting)
- ✅ No critical errors in logs
- ✅ Database connections are working
- ✅ API endpoints are responding

## 🚨 Common Issues

### Issue: Market data not updating
**Solution:**
```bash
# Restart market-updater
docker compose --profile aws restart market-updater-aws

# Check logs for errors
docker compose --profile aws logs --tail=100 market-updater-aws
```

### Issue: Alerts not sending
**Solution:**
1. Verify `RUNTIME_ORIGIN=AWS` in market-updater-aws
2. Verify `RUN_TELEGRAM=true`
3. Check Telegram bot token and chat ID
4. Run diagnostic script:
```bash
docker compose --profile aws exec -T market-updater-aws python3 backend/scripts/diagnose_telegram_alerts.py
```

### Issue: Services not starting
**Solution:**
```bash
# Check logs
docker compose --profile aws logs backend-aws
docker compose --profile aws logs market-updater-aws

# Rebuild from scratch
docker compose --profile aws down
docker compose --profile aws build --no-cache
docker compose --profile aws up -d
```

## 📝 Notes

- The fixes for `market_updater.py` (Binance symbol normalization and Crypto.com fallback) are already in the codebase
- The rollback fixes in `routes_dashboard.py` are already committed and pushed
- After deploy, wait at least 5-10 minutes for market data to update (market-updater runs on a schedule)
- Check logs regularly to ensure no errors are occurring




