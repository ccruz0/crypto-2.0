# Deployment Checklist: NordVPN to Direct AWS Elastic IP Migration

## Pre-Deployment Review ✅

- [x] `.env.aws` updated with new Elastic IP `47.130.143.159`
- [x] `USE_CRYPTO_PROXY=false` configured
- [x] `docker-compose.yml` backend-aws service no longer depends on gluetun
- [x] Backend code defaults to `USE_CRYPTO_PROXY=false`
- [x] IP references updated in `backend/app/core/environment.py`
- [x] IP references updated in `frontend/src/lib/environment.ts`
- [x] Migration report created

## Deployment Steps

### Step 1: Verify AWS Elastic IP Whitelist
**CRITICAL:** Ensure Crypto.com Exchange API key whitelist includes:
- ✅ `47.130.143.159` (NEW Elastic IP)

### Step 2: Update sync_to_aws.sh (Optional)
The `sync_to_aws.sh` script still references the old IP. Update if needed:
```bash
EC2_HOST_PRIMARY="47.130.143.159"
```

### Step 3: Deploy to AWS

#### Option A: Using sync_to_aws.sh (Recommended)
```bash
./sync_to_aws.sh
```

This script will:
1. Build Docker images locally
2. Sync project files to AWS
3. Deploy and restart services

#### Option B: Manual Deployment
```bash
# 1. Sync files to AWS
rsync -avz --exclude='node_modules' --exclude='.git' \
  ./ ubuntu@47.130.143.159:~/automated-trading-platform/

# 2. SSH to AWS
ssh ubuntu@47.130.143.159

# 3. On AWS server, restart services
cd ~/automated-trading-platform
docker compose --profile aws down
docker compose --profile aws up -d --build backend-aws market-updater-aws
```

### Step 4: Verify Deployment

#### Check Service Status
```bash
ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws ps"
```

Expected:
- ✅ `backend-aws` should be running and healthy
- ✅ `backend-aws` should NOT depend on `gluetun`
- ✅ `market-updater-aws` should be running

#### Check Backend Logs
```bash
ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws logs backend-aws --tail=50"
```

Look for:
- ✅ `CryptoComTradeClient initialized - Live Trading: True`
- ✅ `Using base URL: https://api.crypto.com/exchange/v1` (NOT proxy URL)
- ❌ Should NOT see: `CryptoComTradeClient using PROXY at...`

#### Test API Connection
```bash
# From local machine
curl http://47.130.143.159:8002/health
curl http://47.130.143.159:8002/api/health
```

#### Verify Direct Connection
```bash
ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws exec backend-aws env | grep -E 'USE_CRYPTO_PROXY|EXCHANGE_CUSTOM_BASE_URL|CRYPTO_REST_BASE'"
```

Expected output:
```
USE_CRYPTO_PROXY=false
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
CRYPTO_REST_BASE=https://api.crypto.com/exchange/v1
```

### Step 5: Test Crypto.com Exchange Connection

Monitor backend logs for successful API calls:
```bash
ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws logs backend-aws -f"
```

Test endpoints that use Crypto.com Exchange API and verify they work without proxy errors.

## Rollback Plan (If Needed)

If issues occur:

1. **Stop services:**
   ```bash
   ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws down"
   ```

2. **Restore previous .env.aws** (if backed up)

3. **Restart with previous configuration:**
   ```bash
   ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws up -d"
   ```

## Success Criteria

- [ ] Backend connects directly to Crypto.com Exchange API
- [ ] No proxy-related errors in logs
- [ ] API calls to Crypto.com Exchange succeed
- [ ] Backend health checks pass
- [ ] Services start without gluetun dependency

## Post-Deployment

- [ ] Update documentation if needed
- [ ] Remove gluetun container (optional, can be done later)
- [ ] Monitor for 24-48 hours to ensure stability




















