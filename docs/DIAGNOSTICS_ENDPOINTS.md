# Diagnostics Endpoints

## Available Endpoints

### GET /api/diagnostics/whoami
Safe diagnostic endpoint to identify which backend service is running.

**Gating:** `ENVIRONMENT=local` OR `PORTFOLIO_DEBUG=1`

**Response (when enabled):**
```json
{
  "timestamp_utc": "2026-01-06T...",
  "service_info": {
    "process_id": 123,
    "container_name": "...",
    "runtime_origin": "LOCAL",
    "environment": "local",
    "app_version": "...",
    "build_time": "..."
  },
  "env_files_loaded": [".env", ".env.local"],
  "credential_info": {...},
  "client_path": "..."
}
```

**Response (when disabled):**
```json
{
  "detail": "Diagnostic endpoint disabled. Set ENVIRONMENT=local or PORTFOLIO_DEBUG=1 to enable."
}
```
Status: 403

### GET /api/diagnostics/portfolio/reconcile
Portfolio reconcile evidence endpoint. Returns safe reconcile data (no secrets).

**Gating:** `ENVIRONMENT=local` OR `PORTFOLIO_DEBUG=1`

**Response:**
```json
{
  "exchange": "crypto_com",
  "total_value_usd": 12345.67,
  "portfolio_value_source": "exchange:result.data[0].walletBalanceAfterHaircut",
  "raw_fields": {
    "walletBalanceAfterHaircut": 12345.67,
    "marginEquity": 12000.00,
    ...
  },
  "candidates": {
    "exchange_wallet_balance_after_haircut": 12345.67,
    "derived_collateral_minus_borrowed": 11000.00
  },
  "chosen": {
    "value": 12345.67,
    "field_path": "result.data[0].walletBalanceAfterHaircut",
    "priority": 0,
    "source_key": "result.data[0].walletBalanceAfterHaircut"
  }
}
```

## Configuration

### Enable Diagnostics

**In docker-compose.yml (backend-aws service):**
```yaml
environment:
  - PORTFOLIO_DEBUG=1
  - PORTFOLIO_RECONCILE_DEBUG=1
```

**Or via environment variable:**
```bash
export PORTFOLIO_DEBUG=1
export PORTFOLIO_RECONCILE_DEBUG=1
```

### Verify Endpoints Are Registered

```bash
cd ~/automated-trading-platform
curl -sS http://localhost:8002/openapi.json | python3 -m json.tool | grep -A 2 "diagnostics/portfolio/reconcile"
curl -sS http://localhost:8002/openapi.json | python3 -m json.tool | grep -A 2 "diagnostics/whoami"
```

**Expected:** Both paths should appear in the OpenAPI schema.

### Test Endpoints

```bash
cd ~/automated-trading-platform
# Test whoami
curl -sS http://localhost:8002/api/diagnostics/whoami | python3 -m json.tool

# Test reconcile (requires PORTFOLIO_DEBUG=1 or ENVIRONMENT=local)
curl -sS http://localhost:8002/api/diagnostics/portfolio/reconcile | python3 -m json.tool
```

**Expected:**
- Status 200 with JSON response (when enabled)
- Status 403 with error message (when disabled)

## Safety

- **No secrets exposed:** Endpoints never return API keys, secrets, account IDs, or full raw exchange payloads
- **Gated access:** Only enabled in local environment or when `PORTFOLIO_DEBUG=1`
- **Safe fields only:** Reconcile endpoint returns only numeric equity/balance fields and computed values


