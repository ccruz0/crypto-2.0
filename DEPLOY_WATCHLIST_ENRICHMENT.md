# Deployment Instructions: Watchlist Enrichment Fix

## Changes Deployed

1. **Watchlist Enrichment** - `/api/dashboard` endpoints now enrich with MarketData
2. **Transaction Handling** - Fixed database transaction rollback issues
3. **Consistency Report** - Fixed path resolution and schema issues
4. **Nginx Configuration** - Updated monitoring endpoint cache control

## Deployment Steps

### 1. Pull Latest Code (on AWS server)

```bash
cd /home/ubuntu/automated-trading-platform
git pull origin main
```

### 2. Rebuild Backend Docker Image

```bash
docker compose build backend-aws
```

### 3. Restart Backend Service

```bash
docker compose restart backend-aws
```

### 4. Verify Backend is Running

```bash
docker compose ps backend-aws
docker compose logs backend-aws --tail 50
```

### 5. Update Nginx Configuration (if changed)

```bash
# Copy nginx config to server
sudo cp nginx/dashboard.conf /etc/nginx/sites-available/dashboard.hilovivo.com

# Test nginx configuration
sudo nginx -t

# Reload nginx if test passes
sudo systemctl reload nginx
```

### 6. Verify Deployment

#### Test Watchlist Enrichment

```bash
# Run test script
python3 test_watchlist_enrichment.py
```

Expected output:
- ✅ All tests passing
- ✅ 5/5 items enriched in /api/dashboard
- ✅ 5/5 coins enriched in /api/market/top-coins-data
- ✅ 0 mismatches between endpoints

#### Test API Endpoints

```bash
# Test /api/dashboard
curl -s http://localhost:8002/api/dashboard | jq '.[0] | {symbol, price, rsi, ma50, ma200, ema10}'

# Test monitoring endpoint
curl -s http://localhost:8002/api/monitoring/summary | jq '{backend_health, errors}'
```

Expected:
- `backend_health: "healthy"`
- `errors: []`
- All watchlist items have non-null values for price, rsi, ma50, ma200, ema10

### 7. Monitor Logs

```bash
# Watch backend logs for errors
docker compose logs -f backend-aws | grep -i "error\|exception\|rollback"

# Watch for enrichment logs
docker compose logs -f backend-aws | grep -i "enrich\|marketdata"
```

## Rollback Instructions

If issues occur, rollback to previous version:

```bash
# Revert to previous commit
git revert HEAD

# Rebuild and restart
docker compose build backend-aws
docker compose restart backend-aws
```

## Verification Checklist

- [ ] Backend service running
- [ ] No errors in logs
- [ ] `/api/dashboard` returns enriched values
- [ ] `/api/monitoring/summary` shows "healthy"
- [ ] Test script passes all tests
- [ ] Frontend displays values correctly (no "-" for indicators)

## Post-Deployment

1. **Monitor for 24 hours** - Watch for any transaction errors
2. **Check consistency report** - Run watchlist consistency check
3. **Verify frontend** - Confirm watchlist table shows all values

## Support

If issues occur:
1. Check backend logs: `docker compose logs backend-aws`
2. Run diagnostic: `python3 test_watchlist_enrichment.py`
3. Check monitoring: `curl http://localhost:8002/api/monitoring/summary`




