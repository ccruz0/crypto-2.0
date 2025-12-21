# Deployment Instructions: Market Data Enrichment Fix

## Files Changed

1. **backend/app/api/routes_dashboard.py**
   - Fixed enrichment logic to always prefer MarketData values
   - Added volume fields to enrichment (volume_ratio, current_volume, avg_volume, volume_24h)

2. **frontend/src/app/api.ts**
   - Added missing TypeScript interface fields (ma50, ma200, ema10, atr, res_up, res_down)

## Deployment Steps

### Option 1: Using rsync (if SSH is available)

```bash
# Sync backend files
rsync -avz --exclude='venv/' --exclude='__pycache__/' --exclude='*.pyc' \
  backend/app/api/routes_dashboard.py \
  ubuntu@175.41.189.249:~/automated-trading-platform/backend/app/api/

# Restart backend service on AWS
ssh ubuntu@175.41.189.249 'cd ~/automated-trading-platform && docker-compose --profile aws restart backend-aws'
```

### Option 2: Using docker-compose (if on AWS server)

```bash
# SSH into AWS server first
ssh ubuntu@175.41.189.249

# Navigate to project directory
cd ~/automated-trading-platform

# Pull latest code (if using git)
# git pull

# Or manually copy routes_dashboard.py file

# Rebuild and restart backend
docker-compose --profile aws up -d --build backend-aws

# Check logs
docker-compose --profile aws logs -f backend-aws
```

### Option 3: Using deployment script (when SSH is available)

```bash
./deploy_backend_full.sh
```

## What This Fix Does

1. **Enrichment Fix**: Watchlist items now always use MarketData computed values instead of potentially stale database values
2. **Volume Fields**: Volume data (volume_ratio, current_volume, avg_volume) now flows from MarketData to watchlist items
3. **Type Safety**: Frontend TypeScript interfaces updated to match backend data structure

## Verification

After deployment, verify the fix:

1. **Check API response**:
   ```bash
   curl -k https://dashboard.hilovivo.com/api/dashboard | jq '.[0] | {symbol, price, rsi, volume_ratio, ma50}'
   ```

2. **Run diagnostic script**:
   ```bash
   python3 check_market_data_via_api.py
   ```

3. **Expected results**:
   - Values should show instead of "-" (this is already working)
   - Volume fields should appear when MarketData has them
   - RSI values should vary (not all 50.0) once market-updater-aws is working

## Note About RSI=50 Default Values

If you still see RSI=50 for most items after deployment:
- This indicates the **market-updater-aws** process needs attention
- Check logs: `docker-compose --profile aws logs market-updater-aws`
- The enrichment fix is working correctly - it's just that MarketData has default values

## Files to Deploy

```
backend/app/api/routes_dashboard.py  (lines 141-169 modified)
frontend/src/app/api.ts              (lines 26-31 added)
```




