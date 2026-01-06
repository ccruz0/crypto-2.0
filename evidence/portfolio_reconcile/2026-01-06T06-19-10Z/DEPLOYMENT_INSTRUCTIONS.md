# Portfolio Cache 500 Error Fix - Deployment Instructions

## Problem
AWS backend returns 500 errors on `/api/dashboard/state` endpoint.

## Root Cause
Portfolio reconcile code crashes when API response shape differs from expected, or when nested structures are missing.

## Fixes Applied
1. **Defensive nested structure scanning**: Added try/except in `scan_for_equity_fields()` for recursive scanning
2. **Always initialize reconcile_data**: Prevents KeyError when debug is disabled
3. **Defensive API response handling**: Check `get_account_summary()` return type before processing
4. **Defensive account types extraction**: Wrapped in try/except
5. **Defensive derived equity calculation**: Safe numeric conversion with fallback
6. **Always include reconcile structure**: When debug enabled, always include (even if empty)

## Files Modified
- `backend/app/services/portfolio_cache.py`

## Deployment Steps

### 1. Commit and Push Changes
```bash
cd ~/automated-trading-platform
git add backend/app/services/portfolio_cache.py
git commit -m "Fix: Add defensive error handling to portfolio_cache to prevent 500 errors"
git push origin main
```

### 2. Deploy to AWS
On AWS instance (via SSM or SSH):
```bash
cd ~/automated-trading-platform
git pull origin main
docker compose --profile aws build backend-aws
docker compose --profile aws restart backend-aws
```

### 3. Enable Reconcile Debug
Add to `.env.aws` or docker-compose.yml backend-aws environment:
```yaml
- PORTFOLIO_RECONCILE_DEBUG=1
```

Then restart:
```bash
docker compose --profile aws restart backend-aws
```

### 4. Verify Fix
```bash
# Health check
curl -sS http://localhost:8002/api/health | python3 -m json.tool

# Dashboard state (should return 200)
curl -sS "http://localhost:8002/api/dashboard/state" | python3 -m json.tool | head -50
```

### 5. Collect Evidence
```bash
cd ~/automated-trading-platform
./evidence/portfolio_reconcile/collect_evidence.sh
```

## Expected Results
- `/api/dashboard/state` returns 200
- `portfolio.total_value_usd` matches Crypto.com UI
- `portfolio.portfolio_value_source` starts with `exchange:`
- `portfolio.reconcile.chosen.field_path` shows which field was used
