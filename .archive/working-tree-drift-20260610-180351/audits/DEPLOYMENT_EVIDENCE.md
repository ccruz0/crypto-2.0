# AWS Deploy-by-Commit Deployment Evidence

**Date**: 2026-01-08  
**Commit**: `66b72a319092e6de09ee3f3cb4f13cf80c4ea0ce`  
**Deployment Method**: Manual (via `scripts/deploy_aws.sh`)

---

## Pre-Deployment Audit

✅ **Secrets Scan**: No secrets found in tracked files  
✅ **Telegram Default**: Verified OFF by default in `telegram_health.py`  
✅ **Deploy Scripts**: Syntax validated, use `set -euo pipefail`  
✅ **Git State**: Clean, `.env.aws` removed from tracking

---

## Deployment Process

1. **Git State**: Reset to `origin/main` (commit `66b72a3`)
2. **Services**: Rebuilt and restarted using `docker compose --profile aws up -d --build`
3. **Health Check**: Validated after 15 second wait

---

## Post-Deployment Verification

### Git State
```
HEAD: 66b72a319092e6de09ee3f3cb4f13cf80c4ea0ce
Branch: main
Status: Clean (matches origin/main)
```

### Service Status
```
NAME                                              STATUS
automated-trading-platform-backend-aws-1          Up 29 seconds (healthy)
automated-trading-platform-frontend-aws-1         Up 15 seconds (healthy)
automated-trading-platform-market-updater-aws-1   Up 29 seconds (healthy)
postgres_hardened                                 Up About a minute (healthy)
postgres_hardened_backup                          Up About a minute (healthy)
```

### Health Endpoint (`/api/health/system`)
```json
{
  "market_data": {
    "status": "PASS",
    "stale_symbols": 0,
    "max_age_minutes": 3.35
  },
  "market_updater": {
    "status": "PASS",
    "is_running": true
  },
  "telegram": {
    "enabled": false,
    "status": "FAIL"
  }
}
```

---

## Pass Criteria Verification

✅ **Market Updater**: `PASS` (status is "PASS", is_running is true)  
✅ **Market Data**: `0` stale symbols, max age 3.35 minutes (< 5 minutes)  
✅ **Telegram**: `enabled: false` (OFF by default, as expected)

---

## Notes

- `.env.aws` was restored from drifted directory (not in git, as expected)
- All services healthy and responding
- Deployment script executed successfully
- Health checks passed all criteria

---

**Deployment Status**: ✅ **SUCCESS**

