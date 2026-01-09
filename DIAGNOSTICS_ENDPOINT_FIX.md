# Diagnostics Endpoint Fix - Verification Summary

## Changes Made

1. **Moved reconcile endpoint** from `routes_dashboard.py` to `routes_diag.py` to keep all diagnostics endpoints together
2. **Updated gating logic** to match `whoami` endpoint: `ENVIRONMENT=local OR PORTFOLIO_DEBUG=1`
3. **Verified PORTFOLIO_DEBUG** is set in `docker-compose.yml` for `backend-aws` service (defaults to 1)
4. **Added tests** for reconcile route registration and gating

## Route Registration

- **Router**: `routes_diag.py` (diagnostics router)
- **Router prefix**: `/api` (set in `main.py` line 549)
- **Route path**: `/diagnostics/portfolio/reconcile`
- **Full URL**: `/api/diagnostics/portfolio/reconcile`

## Configuration

### Single Source of Truth
- **docker-compose.yml** `environment` section is the single source of truth
- Can be overridden by `.env.aws` via `env_file` directive
- Default value: `PORTFOLIO_DEBUG=1` (enabled by default)

### AWS Backend Configuration
In `docker-compose.yml` (backend-aws service, line 252):
```yaml
- PORTFOLIO_DEBUG=${PORTFOLIO_DEBUG:-1}
```

This means:
- If `PORTFOLIO_DEBUG` is set in `.env.aws`, that value is used
- If not set, defaults to `1` (enabled)
- Can be disabled by setting `PORTFOLIO_DEBUG=0` in `.env.aws`

## Verification Commands

### 1. Check route exists in OpenAPI schema
```bash
curl -s http://localhost:8002/openapi.json | python3 -m json.tool | grep -A 5 "reconcile"
```

Expected output should include:
```json
"/api/diagnostics/portfolio/reconcile": {
  "get": {
    ...
  }
}
```

### 2. Test reconcile endpoint (with PORTFOLIO_DEBUG=1)
```bash
curl http://localhost:8002/api/diagnostics/portfolio/reconcile
```

Expected: HTTP 200 with JSON response containing:
- `exchange`
- `total_value_usd`
- `portfolio_value_source`
- `raw_fields`
- `candidates`
- `chosen`

### 3. Test whoami endpoint (with PORTFOLIO_DEBUG=1)
```bash
curl http://localhost:8002/api/diagnostics/whoami
```

Expected: HTTP 200 with JSON response containing:
- `service_info`
- `env_files_loaded`
- `credential_info`

### 4. Test gating (should return 403 when disabled)
```bash
# Temporarily disable (requires restart)
# Set PORTFOLIO_DEBUG=0 in .env.aws or docker-compose.yml
curl http://localhost:8002/api/diagnostics/portfolio/reconcile
```

Expected: HTTP 403 with error message mentioning "PORTFOLIO_DEBUG" or "ENVIRONMENT"

### 5. Run tests
```bash
cd backend
pytest tests/test_diagnostics_routes.py -v
```

Expected: All tests pass, including:
- `test_reconcile_route_registered`
- `test_reconcile_gating_without_debug`
- `test_reconcile_enabled_with_debug`

## Security Notes

- Endpoint is gated by `ENVIRONMENT=local OR PORTFOLIO_DEBUG=1`
- Response contains NO secrets, API keys, account IDs, or full raw exchange payload
- Safe for use in AWS when `PORTFOLIO_DEBUG=1` is explicitly set
- Default enabled in docker-compose.yml for convenience (can be disabled via .env.aws)

## Files Modified

1. `backend/app/api/routes_diag.py` - Added reconcile endpoint
2. `backend/app/api/routes_dashboard.py` - Removed duplicate reconcile endpoint
3. `backend/tests/test_diagnostics_routes.py` - Added reconcile endpoint tests
4. `docker-compose.yml` - Added clarifying comment about PORTFOLIO_DEBUG

