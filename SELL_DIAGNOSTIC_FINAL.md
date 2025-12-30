# SELL Order Diagnostic - Final Implementation

## Summary

Added comprehensive force diagnostic mode that runs ALL SELL order preflight checks even when `sell_signal=False`, providing full visibility into why orders aren't being created.

## Implementation Details

### Code Changes
- **File**: `backend/app/services/signal_monitor.py`
- **Lines added**: ~150 lines (gated behind env flags)
- **Behavior**: 100% unchanged when flags not set

### Preflight Checks Logged

1. **Trade Flags Check**: `trade_enabled`, `trade_amount_usd`, `trade_on_margin`
2. **Trade Validation**: Verifies flags are valid
3. **Balance Check**: Base currency balance vs required quantity
4. **Live Trading Status**: Checks if live trading is enabled
5. **Margin Settings**: Margin/leverage configuration (if margin trading)
6. **Final Decision**: Would order be created? Why/why not?

### Environment Flags

```bash
# Enable for TRX_USDT specifically
FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT

# OR enable for TRX_USDT (alternative)
FORCE_SELL_DIAGNOSTIC=1
```

**Default**: OFF (safe by default)

## Deployment Commands

### 1. Verify Current Code on AWS

```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "\[DIAGNOSTIC\]" /app/app/services/signal_monitor.py
```

**Expected**: Should return 15+ if code is deployed, 0 if not.

### 2. Deploy the Patch

```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws build --no-cache backend-aws && \
docker compose --profile aws up -d --force-recreate backend-aws
```

### 3. Verify Deployment

```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "FORCE_SELL_DIAGNOSTIC" /app/app/services/signal_monitor.py
```

**Expected**: Should return 2 (two env var checks).

### 4. Enable Force Diagnostics

```bash
cd /home/ubuntu/automated-trading-platform && \
echo "FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT" >> .env.aws && \
docker compose --profile aws restart backend-aws
```

### 5. Verify Diagnostics are Running

**Check startup message:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs backend-aws | grep "DIAGNOSTIC.*enabled" | tail -3
```

**Expected output:**
```
🔧 [DIAGNOSTIC] Force sell diagnostics enabled for SYMBOL=TRX_USDT | FORCE_SELL_DIAGNOSTIC=False | FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT | DRY_RUN=True (no orders will be placed)
```

### 6. Watch Diagnostic Logs

**Wait ~30 seconds for next signal monitor cycle, then:**

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
🔍 [DIAGNOSTIC] TRX_USDT FINAL DECISION: would_create_order=NO, DRY_RUN=True (no order will be placed)
🔍 [DIAGNOSTIC] TRX_USDT Order would NOT be created (DRY_RUN): blocking_reasons=Insufficient balance: Available=0.00000000 TRX < Required=35.33568905 TRX
```

## What the Logs Show

### For Each Evaluation Cycle (~30 seconds):

1. **PREFLIGHT CHECK 1**: Current trade flags from database
2. **PREFLIGHT CHECK 2**: Validation of trade flags (PASSED/BLOCKED)
3. **PREFLIGHT CHECK 3**: Balance check with:
   - Base currency (e.g., TRX)
   - Available balance
   - Required quantity
   - Calculation details
4. **PREFLIGHT CHECK 4**: Live trading status
5. **PREFLIGHT CHECK 5**: Margin settings (if margin trading enabled)
6. **FINAL DECISION**: Would order be created? Blocking reasons if not.

## Common Blocking Reasons

1. **Insufficient Balance**: Not enough base currency (TRX) to sell
2. **trade_enabled=False**: Automatic trading disabled
3. **trade_amount_usd not set**: No order size configured
4. **Balance check failed**: API error or account access issue

## Disable Diagnostics

```bash
cd /home/ubuntu/automated-trading-platform && \
# Edit .env.aws and remove FORCE_SELL_DIAGNOSTIC_SYMBOL line, then:
docker compose --profile aws restart backend
```

## Safety Features

✅ **Default OFF**: Requires explicit env flag  
✅ **DRY RUN**: Never places real orders  
✅ **Symbol-specific**: Can target specific symbols  
✅ **Non-intrusive**: Doesn't affect normal operation  
✅ **All existing behavior unchanged** when flags not set

## Verification Checklist

- [ ] Diagnostic strings exist in container (`grep [DIAGNOSTIC]` returns 8+)
- [ ] Env vars are set (`env | grep FORCE_SELL`)
- [ ] Startup log shows "diagnostics enabled"
- [ ] Diagnostic logs appear every ~30 seconds
- [ ] All 5 preflight checks are logged
- [ ] Final decision is logged with blocking reasons
- [ ] No real orders are placed (DRY_RUN=True in all logs)

