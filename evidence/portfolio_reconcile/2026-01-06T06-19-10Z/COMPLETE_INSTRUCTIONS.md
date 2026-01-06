# Complete Portfolio Fix Deployment Instructions

## Current Status

✅ **Phase 1: Commit & Push** - COMPLETE
- Defensive fixes committed: `50cf7b1`
- PORTFOLIO_RECONCILE_DEBUG enabled in docker-compose.yml

⏳ **Phase 2-7**: PENDING (requires AWS access)

## Quick Start

### Option A: Automated Deployment (Recommended)

```bash
cd ~/automated-trading-platform
./deploy_and_verify_portfolio_fix.sh
```

### Option B: Manual Deployment

1. **SSH/SSM into AWS instance**:
   ```bash
   aws ssm start-session --target i-08726dc37133b2454
   ```

2. **On AWS instance**:
   ```bash
   cd ~/automated-trading-platform
   git pull origin main
   docker compose --profile aws build backend-aws
   docker compose --profile aws restart backend-aws
   ```

3. **Verify deployment**:
   ```bash
   docker logs --tail 50 backend-aws | grep -E "(ERROR|Exception|Started)"
   ```

## Verification Steps

### 1. Start SSM Port-Forward (if not active)
```bash
aws ssm start-session \
  --target i-08726dc37133b2454 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["127.0.0.1"],"portNumber":["8002"],"localPortNumber":["8002"]}'
```

### 2. Test Health Endpoint
```bash
curl -sS http://localhost:8002/api/health | python3 -m json.tool
```

### 3. Test Dashboard State (should return 200)
```bash
curl -sS "http://localhost:8002/api/dashboard/state" | python3 -m json.tool | head -100
```

### 4. Collect Evidence
```bash
cd ~/automated-trading-platform
./evidence/portfolio_reconcile/collect_evidence.sh
```

### 5. Verify Portfolio Value
Check `evidence/portfolio_reconcile/<timestamp>/portfolio_extract.txt`:
- `total_value_usd` should match Crypto.com UI
- `portfolio_value_source` should start with `exchange:`
- `reconcile.chosen.field_path` should show the field used

## Expected Results

✅ `/api/dashboard/state` returns 200 (not 500)
✅ `portfolio.total_value_usd` matches Crypto.com UI "Wallet Balance (after haircut)"
✅ `portfolio.portfolio_value_source` starts with `exchange:` (not `derived:`)
✅ `portfolio.reconcile.chosen.field_path` includes "after_haircut" if present
✅ `portfolio.reconcile.raw_fields` contains all equity/balance fields found

## Troubleshooting

### If still getting 500:
1. Check AWS backend logs:
   ```bash
   docker logs --tail 200 backend-aws | grep -A 20 "Traceback\|ERROR\|Exception"
   ```
2. Verify defensive fixes are deployed:
   ```bash
   docker exec backend-aws grep -A 5 "defensive\|try:" /app/app/services/portfolio_cache.py | head -20
   ```

### If reconcile data missing:
1. Verify PORTFOLIO_RECONCILE_DEBUG is enabled:
   ```bash
   docker exec backend-aws env | grep PORTFOLIO_RECONCILE_DEBUG
   ```
2. Should show: `PORTFOLIO_RECONCILE_DEBUG=1`

### If portfolio_value_source is "derived:":
- Check `portfolio.reconcile.raw_fields` for available exchange fields
- Verify API response contains equity/balance fields
- Check logs for: `[RECONCILE] Found X equity/balance fields`
