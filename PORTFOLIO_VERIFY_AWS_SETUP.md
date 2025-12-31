# Portfolio Verification AWS Setup

## Summary

Configured automated portfolio verification to run end-to-end on AWS with hardened diagnostics auth.

## Changes Made

### 1. Docker Compose Configuration

**File**: `docker-compose.yml`

**Added** to `backend-aws` service environment section:
```yaml
- ENABLE_DIAGNOSTICS_ENDPOINTS=${ENABLE_DIAGNOSTICS_ENDPOINTS:-0}
- DIAGNOSTICS_API_KEY=${DIAGNOSTICS_API_KEY}
```

These env vars are loaded from `.env.aws` (via `env_file`) or can be set via environment variables.

### 2. Verification Script

**File**: `verify_portfolio_aws.sh`

**Purpose**: End-to-end verification script that:
1. Ensures diagnostics env vars are set in `.env.aws`
2. Restarts `backend-aws` to load env vars
3. Waits for backend to be healthy
4. Calls verification endpoint (lite)
5. Returns PASS/FAIL with exact diff in USD

## Usage

### Run Verification

```bash
cd /Users/carloscruz/automated-trading-platform
./verify_portfolio_aws.sh
```

### Custom API Key

```bash
DIAGNOSTICS_API_KEY="your-custom-key" ./verify_portfolio_aws.sh
```

### Custom AWS Host

```bash
AWS_HOST="your-aws-host" ./verify_portfolio_aws.sh
```

## Expected Output

```
🔍 Verifying portfolio on AWS...

📝 Step 1: Ensuring diagnostics env vars are set...
✅ Added ENABLE_DIAGNOSTICS_ENDPOINTS=1
✅ Added DIAGNOSTICS_API_KEY

🔄 Step 2: Restarting backend-aws to load env vars...

⏳ Step 3: Waiting for backend to be healthy...
✅ Backend is healthy

🔍 Step 4: Running portfolio verification...

📊 Verification Results:
{
  "pass": true,
  "dashboard_net_usd": 11814.17,
  "crypto_com_net_usd": 11814.15,
  "diff_usd": 0.02,
  "timestamp": "2025-01-18T12:34:56.789Z"
}

==========================================
✅ PASS
Dashboard NET:  $11814.17
Crypto.com NET: $11814.15
Difference:     $0.02
==========================================
```

## Manual Steps (if needed)

### Add Env Vars to .env.aws on AWS

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  echo "ENABLE_DIAGNOSTICS_ENDPOINTS=1" >> .env.aws && \
  echo "DIAGNOSTICS_API_KEY=eJrAlyoA9SleEMAwRpvISw5qekXAfFoTVMxB6Ja-TUA" >> .env.aws'
```

### Restart Backend

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  sudo bash -lc "export ENABLE_DIAGNOSTICS_ENDPOINTS=1 DIAGNOSTICS_API_KEY=\"eJrAlyoA9SleEMAwRpvISw5qekXAfFoTVMxB6Ja-TUA\" && \
  docker compose --profile aws restart backend-aws"'
```

### Run Verification Manually

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  curl -s -H "X-Diagnostics-Key: eJrAlyoA9SleEMAwRpvISw5qekXAfFoTVMxB6Ja-TUA" \
  http://localhost:8002/api/diagnostics/portfolio-verify-lite | jq'
```

## Security Notes

- **Default Disabled**: `ENABLE_DIAGNOSTICS_ENDPOINTS` defaults to `0` (disabled)
- **API Key Required**: Must set `DIAGNOSTICS_API_KEY` in `.env.aws` or environment
- **No Hardcoding**: API key is not hardcoded in docker-compose.yml
- **Gitignored**: `.env.aws` is gitignored for security

## Self-Check (Local Validation)

Before deploying, validate the implementation locally:

```bash
cd /Users/carloscruz/automated-trading-platform
python -m tools.self_check_portfolio_verify
```

This checks:
- docker-compose.yml contains correct env var wiring
- routes_dashboard.py has proper auth guards
- verify_portfolio_aws.sh uses correct headers and endpoints
- Documentation matches implementation

**No external calls are made** - this is a static code validation.

## Troubleshooting

### Backend Not Healthy

If backend doesn't become healthy:
1. Check logs: `ssh hilovivo-aws 'docker compose --profile aws logs backend-aws'`
2. Check if env vars are loaded: `ssh hilovivo-aws 'docker compose --profile aws exec backend-aws env | grep DIAGNOSTICS'`

### 404 Error

If you get 404:
1. Verify `ENABLE_DIAGNOSTICS_ENDPOINTS=1` is set
2. Verify `DIAGNOSTICS_API_KEY` is set
3. Verify header matches: `X-Diagnostics-Key: <key>`

### Verification Fails

If `pass: false`:
- Check `diff_usd` - should be ≤ $5
- Check logs for pricing source issues
- Verify Crypto.com API is accessible

