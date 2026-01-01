# Portfolio Verification Runbook

## Purpose

Automated verification that dashboard "Total Value" (NET equity) matches Crypto.com "Portfolio balance" (NET equity).

## Endpoints

### Full Endpoint
`GET /api/diagnostics/portfolio-verify`

Returns complete verification data including gross assets and borrowed amounts.

### Lite Endpoint (Recommended)
`GET /api/diagnostics/portfolio-verify-lite`

Returns only essential fields: `pass`, `dashboard_net_usd`, `crypto_com_net_usd`, `diff_usd`, `timestamp`.

**Security**: Protected by:
- `ENABLE_DIAGNOSTICS_ENDPOINTS=1` environment variable
- `X-Diagnostics-Key` header (must match `DIAGNOSTICS_API_KEY` env var)

**⚠️ Important**: Keep `ENABLE_DIAGNOSTICS_ENDPOINTS=0` unless actively using diagnostics endpoints.

## Response Format

### Lite Endpoint Response
```json
{
  "pass": true,
  "dashboard_net_usd": 11814.17,
  "crypto_com_net_usd": 11814.15,
  "diff_usd": 0.02,
  "timestamp": "2025-01-18T12:34:56.789Z"
}
```

### Full Endpoint Response
```json
{
  "dashboard_net_usd": 11748.16,
  "dashboard_gross_usd": 12176.72,
  "dashboard_collateral_usd": 11748.16,
  "dashboard_borrowed_usd": 0.0,
  "crypto_com_net_usd": 11748.15,
  "crypto_com_gross_usd": 12176.70,
  "crypto_com_collateral_usd": 11748.15,
  "crypto_com_borrowed_usd": 0.0,
  "diff_usd": 0.01,
  "diff_pct": 0.0001,
  "pass": true,
  "tolerance_usd": 5.0,
  "timestamp": "2025-01-18T12:34:56.789Z"
}
```

### Full Endpoint with Breakdown (include_breakdown=1 & PORTFOLIO_DEBUG=1)
```json
{
  "dashboard_net_usd": 11748.16,
  "crypto_com_net_usd": 11748.15,
  "diff_usd": 0.01,
  "pass": true,
  "breakdown": [
    {"symbol": "ALGO", "quantity": 1234.5678, "raw_value_usd": 1500.00, "haircut": 0.3333, "collateral_value_usd": 1000.00},
    {"symbol": "BTC", "quantity": 0.12345678, "raw_value_usd": 5000.00, "haircut": 0.0625, "collateral_value_usd": 4687.50},
    {"symbol": "USD", "quantity": 1000.0, "raw_value_usd": 1000.00, "haircut": 0.0000, "collateral_value_usd": 1000.00}
  ]
}
```

**Fields**:
- `dashboard_net_usd`: NET equity from cached portfolio (same as UI "Total Value")
- `crypto_com_net_usd`: NET equity calculated fresh from Crypto.com API
- `diff_usd`: Difference (dashboard - crypto_com)
- `diff_pct`: Percentage difference (full endpoint only)
- `pass`: `true` if `abs(diff_usd) <= 5.0`
- `tolerance_usd`: Maximum allowed difference ($5, full endpoint only)

**Portfolio Value Source**:
The dashboard portfolio response includes `portfolio_value_source` field indicating the calculation method:
- `"exchange_margin_equity"`: Uses Crypto.com's pre-computed margin equity/wallet balance (most accurate, includes all adjustments)
- `"derived_collateral_minus_borrowed"`: Fallback calculation using (collateral - borrowed) when exchange field is unavailable

## Local Verification

### Step 1: Set Environment Variables
```bash
cd /Users/carloscruz/automated-trading-platform
export ENABLE_DIAGNOSTICS_ENDPOINTS=1
export DIAGNOSTICS_API_KEY="your-secret-key-here"  # Generate a secure random key
export VERIFICATION_DEBUG=1  # Optional: for detailed logging
```

### Step 2: Start Backend
```bash
# If using uvicorn directly
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Or if using docker compose
docker compose up backend
```

### Step 3: Call Endpoint (with auth header)

**Lite endpoint (recommended)**:
```bash
curl -s -H "X-Diagnostics-Key: your-secret-key-here" \
  http://localhost:8000/api/diagnostics/portfolio-verify-lite | jq
```

**Full endpoint**:
```bash
curl -s -H "X-Diagnostics-Key: your-secret-key-here" \
  http://localhost:8000/api/diagnostics/portfolio-verify | jq
```

### Expected Output (Lite)
```json
{
  "pass": true,
  "dashboard_net_usd": 11814.17,
  "crypto_com_net_usd": 11814.15,
  "diff_usd": 0.02,
  "timestamp": "2025-01-18T12:34:56.789Z"
}
```

### Step 4: Check Logs
Look for structured log line:
```
[VERIFICATION_DEBUG] Portfolio verify-lite: dashboard_net=$11,814.17, crypto_com_net=$11,814.15, diff=$0.02, pass=True
```

## AWS Verification

### Step 1: Enable Diagnostics on AWS
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sudo bash -lc "export ENABLE_DIAGNOSTICS_ENDPOINTS=1 DIAGNOSTICS_API_KEY=your-secret-key-here VERIFICATION_DEBUG=1 && docker compose --profile aws restart backend-aws"'
```

**⚠️ Important**: Set `DIAGNOSTICS_API_KEY` in your AWS environment securely (e.g., via AWS Secrets Manager or environment file).

### Step 2: Call Endpoint (with auth header)

**Lite endpoint (recommended)**:
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && curl -s -H "X-Diagnostics-Key: your-secret-key-here" http://localhost:8000/api/diagnostics/portfolio-verify-lite | jq'
```

**Full endpoint**:
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && curl -s -H "X-Diagnostics-Key: your-secret-key-here" http://localhost:8000/api/diagnostics/portfolio-verify | jq'
```

### Alternative: Direct HTTP Call (if exposed)
```bash
curl -s -H "X-Diagnostics-Key: your-secret-key-here" \
  https://dashboard.hilovivo.com/api/diagnostics/portfolio-verify-lite | jq
```

### One-liner (AWS)
```bash
# Lite endpoint
ssh hilovivo-aws 'curl -s -H "X-Diagnostics-Key: $DIAGNOSTICS_API_KEY" http://localhost:8000/api/diagnostics/portfolio-verify-lite | jq'

# Full endpoint
ssh hilovivo-aws 'curl -s -H "X-Diagnostics-Key: $DIAGNOSTICS_API_KEY" http://localhost:8000/api/diagnostics/portfolio-verify | jq'
```

## Interpretation

### Pass (pass=true)
- ✅ Dashboard matches Crypto.com within $5 tolerance
- ✅ System is working correctly
- ✅ No action needed

### Fail (pass=false)
- ❌ Difference > $5
- ⚠️ Possible causes:
  - Stale cache (dashboard cache not updated)
  - Price source mismatch (using external prices instead of Crypto.com)
  - Calculation error
  - Crypto.com API returned different data

### Troubleshooting Failures

1. **Check cache freshness**:
   ```bash
   curl -s http://localhost:8000/api/dashboard/state | jq '.portfolio_last_updated'
   ```

2. **Force cache refresh**:
   ```bash
   curl -X POST http://localhost:8000/api/account/balance?exchange=CRYPTO_COM
   ```

3. **Check pricing source**:
   - Enable `PORTFOLIO_DEBUG=1` and check logs
   - Verify all prices come from `crypto_com_*` sources

4. **Compare values**:
   - `dashboard_net_usd` vs `crypto_com_net_usd`
   - `dashboard_gross_usd` vs `crypto_com_gross_usd`
   - `dashboard_borrowed_usd` vs `crypto_com_borrowed_usd`

## CLI Tool Usage

### Basic Usage (Lite Endpoint)
```bash
cd /Users/carloscruz/automated-trading-platform/backend
export DIAGNOSTICS_API_KEY="your-secret-key-here"
python -m tools.verify_portfolio
```

### With Custom Endpoint
```bash
python -m tools.verify_portfolio --endpoint https://dashboard.hilovivo.com --key your-secret-key-here
```

### Full Endpoint
```bash
python -m tools.verify_portfolio --full
```

### JSON Output
```bash
python -m tools.verify_portfolio --json
```

## CI/CD Integration

### Example: GitHub Actions
```yaml
- name: Verify Portfolio Match
  env:
    DIAGNOSTICS_API_KEY: ${{ secrets.DIAGNOSTICS_API_KEY }}
  run: |
    export ENABLE_DIAGNOSTICS_ENDPOINTS=1
    response=$(curl -s -H "X-Diagnostics-Key: $DIAGNOSTICS_API_KEY" \
      http://localhost:8000/api/diagnostics/portfolio-verify-lite)
    pass=$(echo $response | jq -r '.pass')
    if [ "$pass" != "true" ]; then
      echo "Portfolio verification failed"
      echo $response | jq
      exit 1
    fi
```

### Example: Cron Job (AWS)
```bash
#!/bin/bash
cd /home/ubuntu/automated-trading-platform
export ENABLE_DIAGNOSTICS_ENDPOINTS=1
export DIAGNOSTICS_API_KEY="your-secret-key-here"  # Set securely
result=$(curl -s -H "X-Diagnostics-Key: $DIAGNOSTICS_API_KEY" \
  http://localhost:8000/api/diagnostics/portfolio-verify-lite)
pass=$(echo $result | jq -r '.pass')
if [ "$pass" != "true" ]; then
  echo "ALERT: Portfolio mismatch detected"
  echo $result | jq
  # Send alert (email, Slack, etc.)
fi
```

## Security Notes

- **Read-only**: Endpoints do NOT modify any data
- **Safe**: Can be called frequently without side effects
- **Source of truth**: Crypto.com API is always the reference
- **Tolerance**: $5 accounts for rounding differences and timing
- **Auth**: Requires `X-Diagnostics-Key` header matching `DIAGNOSTICS_API_KEY` env var
- **Default disabled**: Keep `ENABLE_DIAGNOSTICS_ENDPOINTS=0` unless actively using diagnostics
- **404 on failure**: Returns 404 (not 401) to reduce endpoint discoverability
- **No key logging**: API key is never logged

## Generating a Secure API Key

```bash
# Generate a random 32-character key
openssl rand -hex 16

# Or use Python
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set this as `DIAGNOSTICS_API_KEY` in your environment.

