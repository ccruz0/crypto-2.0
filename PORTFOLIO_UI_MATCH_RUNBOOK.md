# Portfolio UI Match Runbook

## Goal
Make Portfolio "Total Value" match Crypto.com Exchange UI "Wallet Balance (after haircut)" on AWS.

## Prerequisites
- SSM port-forward active to AWS backend (port 8002)
- PORTFOLIO_RECONCILE_DEBUG=1 enabled on AWS backend

## Step 1: Start Port-Forward

```bash
cd ~/automated-trading-platform
aws ssm start-session \
  --target i-08726dc37133b2454 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["127.0.0.1"],"portNumber":["8002"],"localPortNumber":["8002"]}'
```

**Keep this terminal open.**

## Step 2: Verify AWS Connection

```bash
cd ~/automated-trading-platform
curl -i http://localhost:8002/api/health | grep -E "(HTTP|X-ATP-Backend)"
```

**Expected**: Headers show `X-ATP-Backend-Commit` and `X-ATP-Backend-Buildtime` (not "unknown").

## Step 3: Run Evidence Script

```bash
cd ~/automated-trading-platform
python3 evidence/portfolio_reconcile/fetch_reconcile_evidence.py --api-base-url http://localhost:8002
```

This creates a timestamped folder under `evidence/portfolio_reconcile/` with:
- `dashboard_state.json` - Full dashboard state
- `reconcile_diagnostics.json` - Diagnostics endpoint response (if available)
- `summary.txt` - Human-readable summary

## Step 4: Check Results

Open `evidence/portfolio_reconcile/<timestamp>/summary.txt` and check:

1. **Portfolio Value Source**: Should start with `exchange:` (not `derived:`)
2. **Chosen Field Path**: Should show the exact field used
3. **Top 30 Raw Fields**: Lists all discovered equity/balance fields

## Step 5: If Still Derived

If `portfolio_value_source` starts with `derived:`, you need to set an override:

### 5a) Identify the Correct Field

Look at `summary.txt` or `reconcile_diagnostics.json` for fields that likely match "Wallet Balance (after haircut)":

- Look for fields containing: `after_haircut`, `afterHaircut`, `wallet_balance`, `walletBalance`
- Check the values - the one matching Crypto.com UI is the correct field

### 5b) Set Override on AWS

**Via SSM shell:**

```bash
cd ~/automated-trading-platform
aws ssm start-session --target i-08726dc37133b2454
```

**Inside SSM shell:**

```bash
cd ~/automated-trading-platform
# Edit docker-compose.yml or .env.aws
# Add: PORTFOLIO_EQUITY_FIELD_OVERRIDE="field_path_here"
# Example: PORTFOLIO_EQUITY_FIELD_OVERRIDE="result.data[0].walletBalanceAfterHaircut"

# Restart backend
docker compose --profile aws restart backend-aws
exit
```

### 5c) Verify Override

```bash
cd ~/automated-trading-platform
python3 evidence/portfolio_reconcile/fetch_reconcile_evidence.py --api-base-url http://localhost:8002
```

Check `summary.txt`:
- `portfolio_value_source` should start with `exchange:` and include the override field path
- `total_value_usd` should match Crypto.com UI "Wallet Balance (after haircut)"

## Acceptance Criteria

✅ `/api/dashboard/state` returns 200  
✅ `portfolio.total_value_usd` matches Crypto.com UI "Wallet Balance (after haircut)" (within $1)  
✅ `portfolio.portfolio_value_source` starts with `exchange:` (not `derived:`)  
✅ `portfolio.reconcile.chosen.field_path` shows the exact exchange field used  
✅ Evidence files exist in `evidence/portfolio_reconcile/<timestamp>/`

## Troubleshooting

### Port 8002 not accessible
```bash
cd ~/automated-trading-platform
lsof -nP -iTCP:8002 -sTCP:LISTEN
# Stop any local containers using port 8002
```

### Diagnostics endpoint returns 403
- Ensure `ENVIRONMENT=local` OR `PORTFOLIO_DEBUG=1` on AWS backend
- Check: `docker exec backend-aws env | grep -E "(ENVIRONMENT|PORTFOLIO_DEBUG)"`

### Override not working
- Verify field path matches exactly (case-sensitive, including dots/brackets)
- Check backend logs: `docker compose --profile aws logs backend-aws | grep OVERRIDE`
- Ensure backend was restarted after setting override

