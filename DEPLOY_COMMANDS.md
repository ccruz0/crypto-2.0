# Deploy Commands - Execute on AWS Server

## Quick Deploy (Copy and paste on AWS server)

```bash
cd ~/automated-trading-platform

# Pull latest code
git pull origin main

# Rebuild services with latest code
docker compose --profile aws build --no-cache backend-aws market-updater-aws

# Restart services
docker compose --profile aws up -d backend-aws market-updater-aws

# Wait for services to start
sleep 15

# Check status
docker compose --profile aws ps backend-aws market-updater-aws
```

## Verify Deployment

### Check Market Data
```bash
docker compose --profile aws exec -T backend-aws python3 << 'PYTHON_SCRIPT'
from app.database import SessionLocal
from app.models.market_price import MarketData

db = SessionLocal()
try:
    md_count = db.query(MarketData).filter(MarketData.rsi.isnot(None)).count()
    total_md = db.query(MarketData).count()
    print(f"MarketData: {total_md} total, {md_count} with RSI")
    
    sample = db.query(MarketData).filter(MarketData.rsi.isnot(None)).limit(5).all()
    print("\nSample symbols:")
    for md in sample:
        print(f"  {md.symbol}: RSI={md.rsi:.2f}, Price={md.price:.4f if md.price else 'None'}")
finally:
    db.close()
PYTHON_SCRIPT
```

### Check Alerts Configuration
```bash
# Check environment variables
docker compose --profile aws exec -T market-updater-aws env | grep -E "TELEGRAM|RUNTIME_ORIGIN|RUN_TELEGRAM"

# Check recent logs
docker compose --profile aws logs --tail=30 market-updater-aws | grep -E "RSI|MarketData|ERROR|WARNING"
```

### Check Service Health
```bash
# All services status
docker compose --profile aws ps

# Backend health
docker compose --profile aws exec backend-aws curl -f http://localhost:8002/ping_fast
```

## Recent Changes Deployed

1. **routes_dashboard.py**: 
   - Improved error handling in `_get_market_data_for_symbol`
   - Better symbol normalization (uppercase)
   - Enhanced exception handling

2. **market_updater.py** (already in codebase):
   - Fixed Binance symbol normalization
   - Added Crypto.com fallback for insufficient OHLCV data

3. **Transaction rollback fixes** (already committed):
   - Explicit rollback on database query errors
   - Prevents "transaction aborted" errors




