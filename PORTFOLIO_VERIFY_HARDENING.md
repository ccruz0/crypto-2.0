# Portfolio Verification Hardening Summary

## Root Cause

**Mismatch happened because we were displaying GROSS assets while Crypto.com displays NET equity.**

This has been fixed. The verification endpoints ensure the fix remains correct by comparing dashboard NET equity with Crypto.com NET equity.

## Minimal Diffs

### A) Internal Diagnostics Auth

**File**: `backend/app/api/routes_dashboard.py` (lines 2821-2844)

**Added**:
- `_verify_diagnostics_auth()` function that:
  - Checks `ENABLE_DIAGNOSTICS_ENDPOINTS=1`
  - Requires `X-Diagnostics-Key` header matching `DIAGNOSTICS_API_KEY` env var
  - Returns 404 (not 401) to reduce endpoint discoverability
  - Does not log the key

**Updated**:
- Both endpoints now require `request: Request` parameter
- Both endpoints call `_verify_diagnostics_auth(request)` before processing

### B) Lightweight Endpoint

**File**: `backend/app/api/routes_dashboard.py` (lines 3040-3170)

**Added**:
- New endpoint: `GET /api/diagnostics/portfolio-verify-lite`
- Returns only: `pass`, `dashboard_net_usd`, `crypto_com_net_usd`, `diff_usd`, `timestamp`
- No per-asset breakdown even if `PORTFOLIO_DEBUG=1`
- Same auth guards as full endpoint

### C) CLI Tool Updates

**File**: `backend/tools/verify_portfolio.py`

**Added**:
- `--key` flag (or reads from `DIAGNOSTICS_API_KEY` env var)
- Defaults to `/portfolio-verify-lite` endpoint
- `--full` flag to use `/portfolio-verify` endpoint
- Adds `X-Diagnostics-Key` header to all requests

### D) Runbook Updates

**File**: `PORTFOLIO_VERIFY_RUNBOOK.md`

**Updated**:
- Added auth requirements and examples
- Added lite endpoint documentation
- Updated all curl examples to include `X-Diagnostics-Key` header
- Added AWS one-liners with headers
- Added security notes and key generation instructions
- Reminder to keep `ENABLE_DIAGNOSTICS_ENDPOINTS=0` unless needed

## Example Commands

### Local (Lite Endpoint)
```bash
cd /Users/carloscruz/automated-trading-platform
export ENABLE_DIAGNOSTICS_ENDPOINTS=1
export DIAGNOSTICS_API_KEY="your-secret-key-here"
curl -s -H "X-Diagnostics-Key: your-secret-key-here" \
  http://localhost:8000/api/diagnostics/portfolio-verify-lite | jq
```

### Local (Full Endpoint)
```bash
curl -s -H "X-Diagnostics-Key: your-secret-key-here" \
  http://localhost:8000/api/diagnostics/portfolio-verify | jq
```

### AWS (Lite Endpoint)
```bash
ssh hilovivo-aws 'curl -s -H "X-Diagnostics-Key: $DIAGNOSTICS_API_KEY" \
  http://localhost:8000/api/diagnostics/portfolio-verify-lite | jq'
```

### AWS (Full Endpoint)
```bash
ssh hilovivo-aws 'curl -s -H "X-Diagnostics-Key: $DIAGNOSTICS_API_KEY" \
  http://localhost:8000/api/diagnostics/portfolio-verify | jq'
```

### CLI Tool
```bash
cd /Users/carloscruz/automated-trading-platform/backend
export DIAGNOSTICS_API_KEY="your-secret-key-here"
python -m tools.verify_portfolio  # Uses lite endpoint by default
python -m tools.verify_portfolio --full  # Uses full endpoint
```

## Sample Output (Lite)

```json
{
  "pass": true,
  "dashboard_net_usd": 11814.17,
  "crypto_com_net_usd": 11814.15,
  "diff_usd": 0.02,
  "timestamp": "2025-01-18T12:34:56.789Z"
}
```

## Security Features

✅ **Auth Guard**: Requires `X-Diagnostics-Key` header  
✅ **404 on Failure**: Returns 404 (not 401) to reduce discoverability  
✅ **No Key Logging**: API key is never logged  
✅ **Default Disabled**: `ENABLE_DIAGNOSTICS_ENDPOINTS=0` by default  
✅ **Read-only**: No data modification  
✅ **Crypto.com Source of Truth**: All values from Crypto.com API  

## Files Modified

1. `backend/app/api/routes_dashboard.py` - Added auth guard and lite endpoint
2. `backend/tools/verify_portfolio.py` - Added auth support and lite endpoint default
3. `PORTFOLIO_VERIFY_RUNBOOK.md` - Updated with auth examples and security notes

**Total**: 3 files modified

## Acceptance Criteria ✅

- ✅ Internal auth guard with `DIAGNOSTICS_API_KEY` and `X-Diagnostics-Key` header
- ✅ Lightweight endpoint returns only essential fields
- ✅ CLI tool defaults to lite endpoint, supports `--full` flag
- ✅ Runbook updated with header usage examples
- ✅ AWS one-liners include headers
- ✅ Reminder to keep endpoints disabled by default
- ✅ Minimal diffs (only security hardening, no refactors)





