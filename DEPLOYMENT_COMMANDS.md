# Price Move Alert Feature - AWS Deployment Commands

## Prerequisites
- Access to AWS deployment server where `docker compose --profile aws` works
- Repository checked out and up to date

## Step-by-Step Deployment

### 1. Pull latest and confirm branch
```bash
cd /path/to/automated-trading-platform
git status
git pull
git log -1 --oneline
```

### 2. Optional: Set overrides in .env.aws (if needed)
```bash
cd /path/to/automated-trading-platform
cat .env.aws | grep -E "PRICE_MOVE_ALERT_PCT|PRICE_MOVE_ALERT_COOLDOWN_SECONDS" || true
```

If not present and you want overrides, add to `.env.aws`:
```
PRICE_MOVE_ALERT_PCT=0.50
PRICE_MOVE_ALERT_COOLDOWN_SECONDS=300
```

(Defaults from docker-compose.yml are 0.50 and 300, so overrides are optional.)

### 3. Deploy (build + up)
```bash
cd /path/to/automated-trading-platform
docker compose --profile aws up -d --build backend-aws market-updater-aws
```

### 4. Restart to ensure env vars load
```bash
cd /path/to/automated-trading-platform
docker compose --profile aws restart backend-aws market-updater-aws
```

### 5. Confirm containers are up
```bash
cd /path/to/automated-trading-platform
docker compose --profile aws ps
```

Expected: Both `backend-aws` and `market-updater-aws` should be running.

### 6. Verify production log proof

**Option A: Check recent logs**
```bash
cd /path/to/automated-trading-platform
docker logs --since 10m market-updater-aws | tail -n 500
```

**Option B: Monitor for PRICE_MOVE_ALERT_SENT (recommended)**
```bash
cd /path/to/automated-trading-platform
docker logs -f market-updater-aws | grep "PRICE_MOVE_ALERT_SENT"
```

**Expected log line format:**
```
PRICE_MOVE_ALERT_SENT symbol=ETH_USDT change_pct=0.63 price=$3400.00 threshold=0.50 cooldown_s=300
```

### 7. If no alerts appear (troubleshooting)

**A) Temporarily lower threshold to force trigger:**
```bash
cd /path/to/automated-trading-platform
# Edit .env.aws and add:
# PRICE_MOVE_ALERT_PCT=0.10

cd /path/to/automated-trading-platform
docker compose --profile aws up -d backend-aws market-updater-aws
cd /path/to/automated-trading-platform
docker compose --profile aws restart backend-aws market-updater-aws
cd /path/to/automated-trading-platform
docker logs -f market-updater-aws | grep "PRICE_MOVE_ALERT_SENT"
```

**B) Check service logs for diagnostics:**
```bash
cd /path/to/automated-trading-platform
docker logs --tail 200 market-updater-aws
cd /path/to/automated-trading-platform
docker logs --tail 200 backend-aws
```

### 8. Record evidence in docs

After capturing a PRICE_MOVE_ALERT_SENT line, update:
- `docs/reports/eth-no-alert-no-buy-rootcause.md`
- Fill in "Deployment Record" section with:
  - Deployment date/time
  - Exact PRICE_MOVE_ALERT_SENT line observed
  - Final threshold values used

## Current Configuration (from docker-compose.yml)

- `PRICE_MOVE_ALERT_PCT`: 0.50 (default)
- `PRICE_MOVE_ALERT_COOLDOWN_SECONDS`: 300 (default, 5 minutes)

Both services configured:
- `backend-aws` (lines 169-170)
- `market-updater-aws` (lines 263-264)




