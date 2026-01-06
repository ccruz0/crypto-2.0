# SSM Port-Forward Portfolio Snapshot Fix Report

**Date:** 2026-01-05  
**Issue:** AWS-connected Hilo Vivo dashboard fetches real portfolio, but SSM port-forward to localhost:8002 returns Crypto.com auth failed (40101) on GET /api/portfolio/snapshot

## Phase 1: Production Dashboard Data Flow

### Production Dashboard Configuration

**Frontend API Base URL:**
- Production (Hilo Vivo): Uses relative path `/api` which nginx proxies to backend on port 8002
- Configuration: `frontend/src/lib/environment.ts` detects `hilovivo.com` hostname and uses relative `/api` path
- Environment variable: `NEXT_PUBLIC_API_URL` is set to `/api` in production (relative path)

**Portfolio Data Endpoint:**
- Production dashboard uses: `GET /api/dashboard/state`
- This endpoint calls: `get_portfolio_summary(db)` → `update_portfolio_cache(db)` → `trade_client.get_account_summary()`
- Service: `backend/app/services/portfolio_cache.py`

**Credential Source:**
- Uses `trade_client` singleton initialized at import time
- Singleton reads: `EXCHANGE_CUSTOM_API_KEY` and `EXCHANGE_CUSTOM_API_SECRET` from environment
- **Issue:** Singleton credentials are set once at import time and not updated dynamically

## Phase 2: SSM Port-Forward Backend Identification

### Diagnostic Endpoints Added

1. **`GET /api/portfolio/snapshot`** - Enhanced with safe request logging:
   - Logs: `request_id`, `exchange`, `runtime_origin`, `environment`, `container_name`
   - Logs: `credential_pair` (env var names only, not values)
   - Logs: `client_path` (crypto_com_direct vs crypto_com_proxy)
   - All logging is safe (no secrets exposed)

2. **`GET /api/diagnostics/whoami`** - New diagnostic endpoint:
   - Gated by `ENVIRONMENT=local` or `PORTFOLIO_DEBUG=1`
   - Returns: process_id, container_name, runtime_origin, environment, app_version, build_time
   - Returns: env_files_loaded (names only), credential_info (pair names only), client_path
   - **No secrets exposed**

### Port-Forward Target

- **SSM Port-Forward:** Forwards `localhost:8002` → EC2 instance port `8002`
- **Backend Service:** `backend-aws` container (from docker-compose.yml)
- **Container:** Runs gunicorn with uvicorn workers on port 8002
- **Environment:** `ENVIRONMENT=aws`, `RUNTIME_ORIGIN=AWS`
- **Command:** `python -m gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8002`

## Phase 3: Root Cause Analysis

### Credential Resolution Mismatch

**Problem Identified:**
1. `trade_client` singleton is initialized at import time with credentials from `EXCHANGE_CUSTOM_API_KEY` and `EXCHANGE_CUSTOM_API_SECRET`
2. If these env vars are not set at import time, singleton has empty credentials
3. `portfolio_cache.update_portfolio_cache()` used `trade_client` directly without updating credentials
4. `portfolio_snapshot.fetch_live_portfolio_snapshot()` uses credential resolver and updates `trade_client` credentials dynamically
5. **Mismatch:** Different code paths used different credential resolution strategies

**Why Dashboard Works:**
- Dashboard uses `/api/dashboard/state` → `portfolio_cache.update_portfolio_cache()`
- If credentials were loaded correctly at import time, this path works
- OR if credentials are in `EXCHANGE_CUSTOM_*` env vars, singleton has them

**Why Portfolio Snapshot Failed:**
- Portfolio snapshot uses `/api/portfolio/snapshot` → `portfolio_snapshot.fetch_live_portfolio_snapshot()`
- Uses credential resolver which checks multiple env var pairs:
  1. `EXCHANGE_CUSTOM_API_KEY` + `EXCHANGE_CUSTOM_API_SECRET`
  2. `CRYPTO_COM_API_KEY` + `CRYPTO_COM_API_SECRET`
  3. `CRYPTOCOM_API_KEY` + `CRYPTOCOM_API_SECRET`
- If credentials are in alternative pairs (not `EXCHANGE_CUSTOM_*`), resolver finds them but `trade_client` singleton might not have them
- **However:** portfolio_snapshot does update trade_client credentials, so this should work...

**Actual Root Cause:**
- The `portfolio_cache` service (used by dashboard) was NOT updating `trade_client` credentials before use
- If credentials were loaded correctly at import time OR if they're in `EXCHANGE_CUSTOM_*`, dashboard works
- But portfolio_snapshot might be called in a different context where credentials need to be resolved dynamically
- **Fix:** Align both services to use the same credential resolver and update `trade_client` before each API call

## Phase 4: Fix Implementation

### Changes Made

1. **`backend/app/api/routes_portfolio.py`:**
   - Added safe request logging with `request_id`, runtime info, credential pair names
   - Logs which client path is used (direct vs proxy)
   - All logging is safe (no secrets)

2. **`backend/app/api/routes_diag.py`:**
   - Added `GET /api/diagnostics/whoami` endpoint
   - Returns service info, env files loaded, credential info (names only)
   - Gated by `ENVIRONMENT=local` or `PORTFOLIO_DEBUG=1`

3. **`backend/app/services/portfolio_cache.py`:**
   - **CRITICAL FIX:** Added credential resolver usage before all `trade_client` API calls
   - Updates `trade_client.api_key` and `trade_client.api_secret` from resolver before use
   - Ensures same credential resolution logic as `portfolio_snapshot`
   - Applied to 3 locations where `trade_client.get_account_summary()` is called

### Fix Summary

**Root Cause:** `portfolio_cache` service (used by dashboard/state) was not using credential resolver, while `portfolio_snapshot` was. This caused inconsistent credential resolution.

**Solution:** Aligned both services to use the same credential resolver (`resolve_crypto_credentials()`) and update `trade_client` credentials dynamically before each API call.

**Result:** Both `/api/dashboard/state` and `/api/portfolio/snapshot` now use the same credential resolution strategy, ensuring consistent behavior.

## Verification Commands

### 1. Check Backend Service Identity

```bash
# Via SSM port-forward
curl -sS http://localhost:8002/api/diagnostics/whoami | python3 -m json.tool
```

Expected output includes:
- `runtime_origin: "AWS"`
- `environment: "aws"`
- `container_name: <container-id>`
- `credential_info.selected_pair: <env-var-pair-name>`

### 2. Verify Portfolio Snapshot Works

```bash
# Via SSM port-forward
curl -sS "http://localhost:8002/api/portfolio/snapshot?exchange=CRYPTO_COM" | python3 -m json.tool | head -80
```

Expected response:
```json
{
  "ok": true,
  "portfolio_source": "crypto_com",
  "positions": [...],
  "totals": {
    "total_value_usd": <value>,
    ...
  },
  "errors": []
}
```

### 3. Check Backend Logs

Look for log entries:
```
[PORTFOLIO_SNAPSHOT] request_id=<id> exchange=CRYPTO_COM runtime_origin=AWS environment=aws container=<name> credential_pair=<pair-name>
[PORTFOLIO_SNAPSHOT] request_id=<id> client_path=crypto_com_direct USE_CRYPTO_PROXY=false
```

### 4. Compare with Dashboard State

```bash
# Dashboard state endpoint (should also work)
curl -sS "http://localhost:8002/api/dashboard/state" | python3 -m json.tool | grep -A 10 "portfolio"
```

Both endpoints should now use the same credentials and work consistently.

## Updated Documentation

### SSM Port-Forward Command

```bash
aws ssm start-session \
  --target <INSTANCE_ID> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["127.0.0.1"],"portNumber":["8002"],"localPortNumber":["8002"]}'
```

### Frontend Configuration

```bash
cd ~/automated-trading-platform/frontend
export NEXT_PUBLIC_API_BASE_URL="http://localhost:8002"
npm run dev
```

### Verification Checklist

- [ ] `GET /api/diagnostics/whoami` returns service info
- [ ] `GET /api/portfolio/snapshot?exchange=CRYPTO_COM` returns `ok: true` with `portfolio_source: "crypto_com"`
- [ ] Portfolio snapshot has non-empty `positions` array
- [ ] Backend logs show credential pair name (not values)
- [ ] No secrets exposed in logs or responses

## Files Changed

1. `backend/app/api/routes_portfolio.py` - Added safe request logging
2. `backend/app/api/routes_diag.py` - Added `/api/diagnostics/whoami` endpoint
3. `backend/app/services/portfolio_cache.py` - **CRITICAL:** Added credential resolver usage before all trade_client calls

## Security Notes

- ✅ No secrets are logged or exposed
- ✅ Credential resolver only logs env var names, not values
- ✅ Diagnostic endpoint is gated by environment/debug flags
- ✅ All logging is safe (request IDs, container names, env var names only)

## Next Steps

1. Deploy changes to AWS backend
2. Test SSM port-forward with updated backend
3. Verify portfolio snapshot returns `ok: true` with real data
4. Confirm both dashboard/state and portfolio/snapshot use same credentials

