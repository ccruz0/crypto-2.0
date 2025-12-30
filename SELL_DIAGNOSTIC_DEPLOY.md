# SELL Diagnostic - Production Deployment Guide

## Overview
Force diagnostic mode runs ALL SELL order preflight checks for a chosen symbol (e.g., TRX_USDT) even when `sell_signal=False`, providing full visibility into why orders aren't being created.

**Safety**: DRY_RUN mode - NEVER places real orders when forced diagnostics are enabled.

## AWS Service Name
**Service**: `backend-aws` (NOT `backend`)

All commands use `backend-aws` service name.

## Exact AWS Deployment Commands

### Step 1: Set Environment Variables

```bash
cd /home/ubuntu/automated-trading-platform && \
echo "FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT" >> .env.aws
```

**Verify env file:**
```bash
cd /home/ubuntu/automated-trading-platform && \
grep FORCE_SELL .env.aws
```

### Step 2: Rebuild with No Cache

```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws build --no-cache backend-aws
```

### Step 3: Deploy with Force Recreate

```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws up -d --force-recreate backend-aws
```

### Step 4: Verify Code is Deployed

**Check diagnostic strings exist:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "\[DIAGNOSTIC\]" /app/app/services/signal_monitor.py
```

**Expected**: Should return 15+ (number of diagnostic log statements)

**Check force diagnostic env checks:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "FORCE_SELL_DIAGNOSTIC" /app/app/services/signal_monitor.py
```

**Expected**: Should return 2 (module-level check + function guard)

**Check startup log:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs backend-aws | grep "DIAGNOSTIC.*enabled"
```

**Expected output:**
```
🔧 [DIAGNOSTIC] Force sell diagnostics enabled for SYMBOL=TRX_USDT | FORCE_SELL_DIAGNOSTIC=False | FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT | DRY_RUN=True (no orders will be placed)
```

### Step 5: Watch Diagnostic Logs

**Wait ~30 seconds for next signal monitor cycle, then:**

```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs -f backend-aws | grep "\[DIAGNOSTIC\].*TRX"
```

**Or filter for FINAL summary lines only:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs -f backend-aws | grep "\[DIAGNOSTIC\].*FINAL.*TRX"
```

## Expected Log Output

Every ~30 seconds, you'll see diagnostic logs including:

```
🔧 [FORCE_DIAGNOSTIC] Running SELL order creation diagnostics for TRX_USDT (signal=WAIT, but diagnostics forced via env flag) | DRY_RUN=True (no order will be placed)
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 1 - Trade flags: trade_enabled=True, trade_amount_usd=10.0, trade_on_margin=True
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 2 - PASSED: trade_enabled=True, trade_amount_usd=$10.00
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 3 - Balance check: base_currency=TRX, available=0.00000000 TRX, required=35.33568905 TRX (from trade_amount_usd=$10.00 / current_price=$0.2831)
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 3 - BLOCKED: Insufficient balance: Available=0.00000000 TRX < Required=35.33568905 TRX
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 4 - Live trading: live_trading=True, dry_run_mode=False
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 5 - PASSED: Open orders: 0/3 for TRX
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 6 - Margin settings: use_margin=True, leverage=10
🔍 [DIAGNOSTIC] FINAL symbol=TRX_USDT decision=BLOCKED reasons=[Insufficient balance: Available=0.00000000 TRX < Required=35.33568905 TRX] required_qty=35.33568905 avail_base=0.00000000 open_orders=OK (0/3) live_trading=True trade_enabled=True DRY_RUN=True
```

## Disable Diagnostics

```bash
cd /home/ubuntu/automated-trading-platform && \
# Edit .env.aws and remove FORCE_SELL_DIAGNOSTIC_SYMBOL line, then:
docker compose --profile aws restart backend-aws
```

## Safety Verification

**Verify no real orders are placed:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs backend-aws | grep "Creating automatic SELL order for TRX_USDT"
```

**Expected**: Should return nothing (no real order creation attempts)

**Verify DRY_RUN guard is working:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs backend-aws | grep "\[DIAGNOSTIC\].*DRY_RUN.*suppressed"
```

**Expected**: Should see "DRY_RUN – order suppressed" messages if guard is triggered

