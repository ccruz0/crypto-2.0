# SELL Diagnostic - Runtime Verification Guide

## How to Prove the Running Container Has the New Code

### 1. Verify Diagnostic Strings Exist in Container

**Check for diagnostic log markers:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "\[DIAGNOSTIC\]" /app/app/services/signal_monitor.py
```

**Expected:** Should return 15+ (number of diagnostic log statements)

**Check for force diagnostic env var checks:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "FORCE_SELL_DIAGNOSTIC" /app/app/services/signal_monitor.py
```

**Expected:** Should return 2 (module-level check + function guard)

**Check for DRY_RUN guard in _create_sell_order:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -A 5 "should_force_diagnostic" /app/app/services/signal_monitor.py | grep -c "diagnostic_mode"
```

**Expected:** Should return 1 (safety guard in _create_sell_order)

### 2. Verify Environment Variables Are Loaded

**Check if env vars are set in container:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) env | grep FORCE_SELL
```

**Expected output (if enabled):**
```
FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT
```

**If no output:** Env vars not set, diagnostics won't run.

### 3. Verify Startup Log Shows Diagnostics Enabled

**Check startup logs:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs backend-aws | grep -i "DIAGNOSTIC.*enabled\|Force sell diagnostics" | tail -3
```

**Expected output:**
```
🔧 [DIAGNOSTIC] Force sell diagnostics enabled for SYMBOL=TRX_USDT | FORCE_SELL_DIAGNOSTIC=False | FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT | DRY_RUN=True (no orders will be placed)
```

**If no output:** Either env vars not set, or code not deployed.

### 4. Verify Diagnostic Logs Appear in Runtime

**Watch logs for diagnostic output (wait ~30 seconds for next cycle):**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs -f backend-aws | grep "\[DIAGNOSTIC\].*TRX"
```

**Expected output (every ~30 seconds):**
```
🔧 [FORCE_DIAGNOSTIC] Running SELL order creation diagnostics for TRX_USDT (signal=WAIT, but diagnostics forced via env flag) | DRY_RUN=True (no order will be placed)
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 1 - Trade flags: trade_enabled=True, trade_amount_usd=10.0, trade_on_margin=True
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 2 - PASSED: trade_enabled=True, trade_amount_usd=$10.00
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 3 - Balance check: base_currency=TRX, available=0.00000000 TRX, required=35.33568905 TRX (from trade_amount_usd=$10.00 / current_price=$0.2831)
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 3 - BLOCKED: Insufficient balance: Available=0.00000000 TRX < Required=35.33568905 TRX
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 4 - Live trading: live_trading=True, dry_run_mode=False
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 5 - PASSED: Open orders: 0/3 for TRX
🔍 [DIAGNOSTIC] TRX_USDT PREFLIGHT CHECK 6 - Margin settings: use_margin=True, leverage=10
🔍 [DIAGNOSTIC] TRX_USDT SUMMARY: symbol=TRX_USDT, trade_enabled=True, live_trading_enabled=True, required_qty=35.33568905 TRX, available_base_balance=0.00000000 TRX, open_orders_status=OK (0/3), final_decision=BLOCKED, blocking_reasons=[Insufficient balance: Available=0.00000000 TRX < Required=35.33568905 TRX], DRY_RUN=True (order suppressed)
```

### 5. Verify DRY_RUN Guard is Working

**Check that no real orders are placed (should see "DRY_RUN" in all logs):**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs backend-aws | grep "\[DIAGNOSTIC\].*TRX.*DRY_RUN" | tail -5
```

**Expected:** Should see multiple "DRY_RUN" messages

**Verify no real order creation attempts:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs backend-aws | grep "Creating automatic SELL order for TRX_USDT" | tail -5
```

**Expected:** Should return nothing (no real order creation attempts)

### 6. Complete Verification Checklist

Run all checks in sequence:

```bash
cd /home/ubuntu/automated-trading-platform && \
echo "=== 1. Code Verification ===" && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "\[DIAGNOSTIC\]" /app/app/services/signal_monitor.py && \
echo "=== 2. Env Vars ===" && \
docker exec $(docker ps -q -f name=backend-aws) env | grep FORCE_SELL && \
echo "=== 3. Startup Log ===" && \
docker compose --profile aws logs backend-aws | grep -i "DIAGNOSTIC.*enabled" | tail -1 && \
echo "=== 4. Runtime Logs (last 30s) ===" && \
docker compose --profile aws logs --since 30s backend-aws | grep "\[DIAGNOSTIC\].*TRX.*SUMMARY" | tail -1
```

**All checks should pass for diagnostics to be working.**

