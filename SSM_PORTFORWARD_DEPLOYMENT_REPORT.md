# SSM Port-Forward Portfolio Fix Deployment Report

**Date:** 2026-01-05  
**Goal:** Deploy portfolio snapshot fix to AWS backend and verify it works via SSM port-forward

## Phase 1: Port-Forward Target Verification

### Instance and Port Configuration
- **EC2 Instance ID:** `i-08726dc37133b2454`
- **Region:** `ap-southeast-1`
- **Port-Forward:** `localhost:8002` → EC2 instance port `8002`
- **SSM Command:**
  ```bash
  aws ssm start-session \
    --target i-08726dc37133b2454 \
    --document-name AWS-StartPortForwardingSessionToRemoteHost \
    --parameters '{"host":["127.0.0.1"],"portNumber":["8002"],"localPortNumber":["8002"]}'
  ```

### Backend Service Identification
- **Service:** `backend-aws` container (Docker Compose)
- **Profile:** `--profile aws`
- **Port:** `8002:8002` (host:container)
- **Command:** `gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8002`
- **Environment:** `ENVIRONMENT=aws`, `RUNTIME_ORIGIN=AWS`

## Phase 2: Deployment

### Files Changed
1. `backend/app/api/routes_portfolio.py` - Added safe request logging
2. `backend/app/api/routes_diag.py` - Added `/api/diagnostics/whoami` endpoint
3. `backend/app/services/portfolio_cache.py` - **CRITICAL:** Added credential resolver usage

### Deployment Method
- **Method:** Direct file copy via SSM + Docker cp
- **Script:** `deploy_portfolio_fix_ssm.sh`
- **Steps:**
  1. Identify backend container
  2. Copy fixed files to container
  3. Restart `backend-aws` service
  4. Verify deployment

### Deployment Commands

```bash
# 1. Verify current state
./verify_portforward_backend.sh

# 2. Deploy fix
./deploy_portfolio_fix_ssm.sh

# 3. Manual verification
curl -sS http://localhost:8002/api/diagnostics/whoami | python3 -m json.tool
curl -sS "http://localhost:8002/api/portfolio/snapshot?exchange=CRYPTO_COM" | python3 -m json.tool | head -80
```

## Phase 3: Verification

### Acceptance Criteria
- [ ] `GET /api/diagnostics/whoami` returns service info (not 404)
- [ ] `GET /api/portfolio/snapshot?exchange=CRYPTO_COM` returns:
  - `ok: true`
  - `portfolio_source: "crypto_com"`
  - `positions.length > 0`
  - `totals` reflect real values

### Verification Commands

```bash
# Check whoami endpoint
curl -sS http://localhost:8002/api/diagnostics/whoami | python3 -m json.tool

# Check portfolio snapshot
curl -sS "http://localhost:8002/api/portfolio/snapshot?exchange=CRYPTO_COM" | python3 -m json.tool

# Check backend logs (via SSM)
aws ssm send-command \
  --instance-ids i-08726dc37133b2454 \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["docker compose --profile aws logs --tail=50 backend-aws"]' \
  --query 'Command.CommandId' --output text
```

## Phase 4: Troubleshooting

### If whoami Returns 404
- **Cause:** Backend does not include the fix
- **Solution:** Run `./deploy_portfolio_fix_ssm.sh`

### If Portfolio Snapshot Returns 40101
- **Cause:** Credential mismatch or missing credentials
- **Check:**
  1. Backend logs for credential pair names (safe logging)
  2. Compare with production dashboard backend
  3. Verify AWS Secrets Manager injection
  4. Check `.env.aws` file is loaded

### If Portfolio Snapshot Returns ok:false
- **Check:** `missing_env` array in response
- **Check:** `errors` array for specific error codes
- **Verify:** Credentials are in the same env var pair as production

## Evidence Collection

### Expected whoami Response
```json
{
  "timestamp_utc": "2026-01-05T...",
  "service_info": {
    "process_id": 12345,
    "container_name": "...",
    "runtime_origin": "AWS",
    "environment": "aws",
    "app_version": "...",
    "build_time": "..."
  },
  "env_files_loaded": [".env", ".env.aws"],
  "credential_info": {
    "selected_pair": "EXCHANGE_CUSTOM_API_KEY/EXCHANGE_CUSTOM_API_SECRET",
    "checked_pairs": [...]
  },
  "client_path": "crypto_com_direct",
  "use_crypto_proxy": false
}
```

### Expected Portfolio Snapshot Response
```json
{
  "ok": true,
  "as_of": "2026-01-05T...",
  "exchange": "CRYPTO_COM",
  "portfolio_source": "crypto_com",
  "message": "Portfolio snapshot: X positions",
  "positions": [
    {
      "asset": "BTC",
      "free": 0.5,
      "locked": 0.0,
      "total": 0.5,
      "price_usd": 65000.0,
      "value_usd": 32500.0,
      "price_source": "crypto_com"
    }
  ],
  "totals": {
    "total_value_usd": 12345.67,
    "total_assets_usd": 15000.00,
    "total_borrowed_usd": 0.0,
    "total_collateral_usd": 15000.00
  },
  "errors": []
}
```

## Next Steps

1. Run verification script to check current state
2. Deploy fix if whoami is missing
3. Verify portfolio snapshot works
4. If 40101 persists, check credential sources and align with production

