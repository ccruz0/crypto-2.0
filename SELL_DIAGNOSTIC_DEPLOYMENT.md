# SELL Order Diagnostic Deployment Guide

## Overview
This patch adds force diagnostic logging for SELL order creation, allowing you to test and debug order creation logic without waiting for a real SELL signal.

## Changes Made

1. **Added Environment Flags** (default OFF):
   - `FORCE_SELL_DIAGNOSTIC=1` - Enables force diagnostics for TRX_USDT
   - `FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT` - Enables force diagnostics for a specific symbol

2. **Force Diagnostic Path**:
   - Runs SELL order creation preflight checks even when `sell_signal=False`
   - Performs balance checks, trade flag validation, and order creation logic checks
   - **DRY RUN mode**: Never places real orders when forced diagnostics are enabled
   - Logs all diagnostic information at INFO level with `[DIAGNOSTIC]` prefix

3. **Enhanced Logging**:
   - All diagnostic logs use consistent `[DIAGNOSTIC]` prefix
   - Startup log shows when diagnostics are enabled
   - All logs are at INFO level (not DEBUG) for visibility

## Deployment Steps

### 1. Verify Code is Deployed

**On AWS, check if diagnostic strings exist in the running container:**

```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "\[DIAGNOSTIC\]" /app/app/services/signal_monitor.py || \
docker exec $(docker ps -q -f name=backend-aws) grep -c "FORCE_SELL_DIAGNOSTIC" /app/app/services/signal_monitor.py
```

**Expected output:** Should show lines containing `[DIAGNOSTIC]` or `FORCE_SELL_DIAGNOSTIC`

**If no output:** Code is not deployed, proceed to step 2.

### 2. Deploy the Patch

**Option A: If using docker-compose with AWS profile (RECOMMENDED):**

```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws build --no-cache backend-aws && \
docker compose --profile aws up -d --force-recreate backend-aws
```

**Option B: If using direct docker commands:**

```bash
cd /home/ubuntu/automated-trading-platform && \
docker build -t backend-aws ./backend && \
docker compose --profile aws up -d --force-recreate backend-aws
```

**Option C: If code is mounted (not in image):**

```bash
cd /home/ubuntu/automated-trading-platform && \
# Just restart to pick up code changes
docker compose --profile aws restart backend-aws
```

### 3. Verify Deployment

**Check that diagnostic strings exist in running container:**

```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "\[DIAGNOSTIC\]" /app/app/services/signal_monitor.py
```

**Expected output:** A number > 0 (should be 15+ diagnostic log lines)

**Verify environment file is loaded:**

```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) env | grep FORCE_SELL
```

**Expected output:** Should show `FORCE_SELL_DIAGNOSTIC` and/or `FORCE_SELL_DIAGNOSTIC_SYMBOL` if set

### 4. Enable Force Diagnostics

**Edit `.env.aws` file (or your environment file):**

```bash
cd /home/ubuntu/automated-trading-platform && \
# Add these lines:
echo "FORCE_SELL_DIAGNOSTIC=1" >> .env.aws
echo "FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT" >> .env.aws
```

**Or set for specific symbol only:**

```bash
cd /home/ubuntu/automated-trading-platform && \
echo "FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT" >> .env.aws
```

**Restart backend to load new env vars:**

```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws restart backend-aws
```

### 5. Verify Diagnostics are Running

**Check startup logs for diagnostic enable message:**

```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs backend-aws | grep -i "FORCE_DIAGNOSTIC\|diagnostics enabled" | tail -5
```

**Expected output:** Should show:
```
🔧 [FORCE_DIAGNOSTIC] SELL order diagnostics enabled | FORCE_SELL_DIAGNOSTIC=True | FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT
```

**Tail logs to see diagnostic output (wait for next signal monitor cycle ~30 seconds):**

```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs -f backend-aws | grep -i "\[DIAGNOSTIC\].*TRX"
```

**Expected output:** Should show diagnostic logs like:
```
🔍 [DIAGNOSTIC] TRX_USDT SELL order creation check (FORCED): ...
🔍 [DIAGNOSTIC] TRX_USDT SELL balance check PASSED: ...
🔍 [DIAGNOSTIC] TRX_USDT SELL order would be CREATED (DRY_RUN): ...
```

## Verification Checklist

- [ ] Diagnostic strings exist in running container (`grep [DIAGNOSTIC]` returns results)
- [ ] Environment variables are set in container (`env | grep FORCE_SELL`)
- [ ] Startup log shows "diagnostics enabled" message
- [ ] Diagnostic logs appear in logs within 30-60 seconds (next signal monitor cycle)
- [ ] Diagnostic logs show `DRY_RUN=True` (no real orders placed)
- [ ] Diagnostic logs include balance check results
- [ ] Diagnostic logs include trade flag status
- [ ] Diagnostic logs include order creation decision

## Troubleshooting

### No diagnostic logs appearing

1. **Check if code is deployed:**
   ```bash
   cd /home/ubuntu/automated-trading-platform && \
   docker exec $(docker ps -q -f name=backend-aws) grep -c "FORCE_SELL_DIAGNOSTIC" /app/app/services/signal_monitor.py
   ```

2. **Check if env vars are set:**
   ```bash
   cd /home/ubuntu/automated-trading-platform && \
   docker exec $(docker ps -q -f name=backend-aws) env | grep FORCE_SELL
   ```

3. **Check if symbol matches:**
   - `FORCE_SELL_DIAGNOSTIC=1` only works for TRX_USDT
   - `FORCE_SELL_DIAGNOSTIC_SYMBOL` must match exactly (case-insensitive)

4. **Check logs for errors:**
   ```bash
   cd /home/ubuntu/automated-trading-platform && \
   docker compose --profile aws logs backend-aws | grep -i "error\|exception" | tail -20
   ```

### Diagnostic logs show but no balance check

- Balance check requires API credentials to be configured
- Check if `trade_client.get_account_summary()` is working
- Look for "API credentials not configured" warnings

### Want to disable diagnostics

**Remove or set to 0:**
```bash
cd /home/ubuntu/automated-trading-platform && \
# Edit .env.aws and remove or set to 0:
FORCE_SELL_DIAGNOSTIC=0
# Or remove the lines entirely
```

**Restart backend:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws restart backend-aws
```

## Testing

The force diagnostic path runs every signal monitor cycle (~30 seconds) for the configured symbol, even when `sell_signal=False`. This allows you to:

1. **Test balance checks** without needing a real SELL signal
2. **Verify trade flags** are correctly configured
3. **See what would happen** if a SELL order was attempted
4. **Debug order creation logic** without placing real orders

All diagnostic output is logged at INFO level with the `[DIAGNOSTIC]` prefix for easy filtering.

