# ETH_USDT No Alert / No Buy Root Cause Analysis

**Date**: 2025-12-31  
**Symbol**: ETH_USDT  
**Issue**: After dashboard toggle, no alert sent and no BUY order placed

## Diagnostic Trace Evidence

### BEFORE Toggle (trade_enabled=False)

```
===== TRACE START ETH_USDT =====
signal_inputs: price=$3396.1700 rsi=37.2 ma50=3377.73 ma200=3716.16 ema10=3397.72 buy_target=None resistance_up=$3464.09 resistance_down=$3328.25 volume=5567.20 avg_volume=3471.95 strategy_id=intraday/conservative
signal_conditions: rsi_ok=True ma_ok=False vol_ok=True target_ok=True price_ok=True strategy_decision=WAIT buy_signal=False sell_signal=False
strategy_params: sl_tp_mode=conservative min_price_change_pct=1.0 trade_amount_usd=100.0 rsi_buy_threshold=40 rsi_sell_threshold=70
ALERT decision=SKIP reason=SKIP_NO_SIGNAL symbol=ETH_USDT side=BUY current_price=$3396.1700 reference_price=None price_change_pct=N/A alert_enabled=True trade_enabled=False throttle_key=ETH_USDT:intraday:conservative:BUY last_sent=None now=2025-12-31T09:48:41.543442+00:00 elapsed=N/A cooldown_threshold=60.0s price_threshold=1.0% force_next_signal=False eval_id=f63bfb63
ALERT decision=SKIP reason=SKIP_NO_SIGNAL symbol=ETH_USDT side=SELL current_price=$3396.1700 reference_price=None price_change_pct=N/A alert_enabled=True trade_enabled=False throttle_key=ETH_USDT:intraday:conservative:SELL last_sent=None now=2025-12-31T09:48:41.543442+00:00 elapsed=N/A cooldown_threshold=60.0s price_threshold=1.0% force_next_signal=False eval_id=f63bfb63
signal_detected: buy=False, sell=False
TRADE decision=SKIP reason=SKIP_NO_SIGNAL blocked_by=TRADE_DISABLED trade_enabled=False signal_exists=False should_create_order=False symbol=ETH_USDT side=BUY current_price=$3396.1700 trade_amount_usd=$100.00
===== TRACE END ETH_USDT =====
```

### AFTER Toggle (trade_enabled=True)

```
===== TRACE START ETH_USDT =====
signal_inputs: price=$3396.1700 rsi=37.2 ma50=3377.73 ma200=3716.16 ema10=3397.72 buy_target=None resistance_up=$3464.09 resistance_down=$3328.25 volume=5567.20 avg_volume=3471.95 strategy_id=intraday/conservative
signal_conditions: rsi_ok=True ma_ok=False vol_ok=True target_ok=True price_ok=True strategy_decision=WAIT buy_signal=False sell_signal=False
strategy_params: sl_tp_mode=conservative min_price_change_pct=1.0 trade_amount_usd=100.0 rsi_buy_threshold=40 rsi_sell_threshold=70
ALERT decision=SKIP reason=SKIP_NO_SIGNAL symbol=ETH_USDT side=BUY current_price=$3396.1700 reference_price=None price_change_pct=N/A alert_enabled=True trade_enabled=True throttle_key=ETH_USDT:intraday:conservative:BUY last_sent=None now=2025-12-31T09:48:42.663552+00:00 elapsed=N/A cooldown_threshold=60.0s price_threshold=1.0% force_next_signal=False eval_id=15139736
ALERT decision=SKIP reason=SKIP_NO_SIGNAL symbol=ETH_USDT side=SELL current_price=$3396.1700 reference_price=None price_change_pct=N/A alert_enabled=True trade_enabled=True throttle_key=ETH_USDT:intraday:conservative:SELL last_sent=None now=2025-12-31T09:48:42.663552+00:00 elapsed=N/A cooldown_threshold=60.0s price_threshold=1.0% force_next_signal=False eval_id=15139736
signal_detected: buy=False, sell=False
TRADE decision=SKIP reason=SKIP_NO_SIGNAL blocked_by=NO_SIGNAL trade_enabled=True signal_exists=False should_create_order=False symbol=ETH_USDT side=BUY current_price=$3396.1700 trade_amount_usd=$100.00
===== TRACE END ETH_USDT =====
```

### With DIAG_FORCE_SIGNAL_BUY=1 (After Toggle)

```
===== TRACE START ETH_USDT =====
signal_inputs: price=$3396.1700 rsi=37.2 ma50=3377.73 ma200=3716.16 ema10=3397.72 buy_target=None resistance_up=$3464.09 resistance_down=$3328.25 volume=5567.20 avg_volume=3471.95 strategy_id=intraday/conservative
signal_conditions: rsi_ok=True ma_ok=False vol_ok=True target_ok=True price_ok=True strategy_decision=WAIT buy_signal=True sell_signal=False
strategy_params: sl_tp_mode=conservative min_price_change_pct=1.0 trade_amount_usd=100.0 rsi_buy_threshold=40 rsi_sell_threshold=70
ALERT decision=EXEC reason=EXEC_ALERT_SENT symbol=ETH_USDT side=BUY current_price=$3396.1700 reference_price=None price_change_pct=N/A alert_enabled=True trade_enabled=True throttle_key=ETH_USDT:intraday:conservative:BUY last_sent=None now=2025-12-31T09:49:01.671630+00:00 elapsed=N/A cooldown_threshold=60.0s price_threshold=1.0% force_next_signal=False eval_id=e783fae6
signal_detected: buy=True, sell=False
TRADE decision=SKIP reason=EXEC_ORDER_BLOCKED_BY_THROTTLE blocked_by=ALERT_NOT_SENT trade_enabled=True signal_exists=True should_create_order=False symbol=ETH_USDT side=BUY current_price=$3396.1700 trade_amount_usd=$100.00
===== TRACE END ETH_USDT =====
```

## Root Cause Analysis

### Primary Issue: No Buy Signal Detected

**Reason**: `SKIP_NO_SIGNAL` (not `SKIP_COOLDOWN_ACTIVE`)

**Signal Condition Breakdown**:
- ✅ `rsi_ok=True` - RSI=37.2 < threshold=40 (passes)
- ❌ `ma_ok=False` - **BLOCKING CONDITION**
- ✅ `vol_ok=True` - Volume ratio passes
- ✅ `target_ok=True` - Target check passes
- ✅ `price_ok=True` - Price validation passes

**Why `ma_ok=False`?**
- Strategy: `intraday/conservative`
- MA50=3377.73, EMA10=3397.72
- **MA50 (3377.73) ≤ EMA10 (3397.72)** - This violates the required condition
- The strategy requires `MA50 > EMA10` for BUY signal (trend confirmation)

**Strategy Parameters**:
- `rsi_buy_threshold=40` (RSI must be < 40)
- `min_price_change_pct=1.0%` (for throttle, not signal detection)
- Strategy config requires MA50 > EMA10 check

### Secondary Issue: Trade Blocked by Alert Dependency

**Finding**: When `DIAG_FORCE_SIGNAL_BUY=1` forces a signal:
- Alert is sent: `ALERT decision=EXEC reason=EXEC_ALERT_SENT`
- But trade is blocked: `TRADE decision=SKIP reason=EXEC_ORDER_BLOCKED_BY_THROTTLE blocked_by=ALERT_NOT_SENT`

**Root Cause**: Trade execution path checks `buy_alert_sent_successfully` flag and blocks order creation if alert was not sent. This creates a coupling where:
1. Alert must be sent before trade can execute
2. If alert sending fails or is delayed, trade is blocked
3. This violates the requirement that "trade execution is never blocked by alert throttle"

## Summary

1. **No Alert Sent**: Because `buy_signal=False` due to `ma_ok=False` (MA50 ≤ EMA10)
2. **No BUY Order**: Because no signal exists (`blocked_by=NO_SIGNAL`)
3. **Trade-Alert Coupling**: When signal exists, trade is blocked by `ALERT_NOT_SENT` guard, indicating trade execution depends on alert sending success

## Recommendations

1. **Signal Detection**: The MA condition (MA50 > EMA10) is correctly blocking the signal. This is expected behavior for the intraday/conservative strategy.

2. **Trade-Alert Decoupling**: Trade execution should NOT be blocked by alert sending. The `ALERT_NOT_SENT` guard should be removed or made optional.

3. **Price Move Alert Channel** (Optional): If requirement is to alert on significant price moves even without buy signal, implement separate `PRICE_MOVE_ALERT` channel with its own throttle bucket.

## Fixes Implemented

### 1. Trade-Alert Decoupling ✅

**Change**: Removed `ALERT_NOT_SENT` guard from trade execution path.

**Location**: `backend/app/services/signal_monitor.py` lines ~2469-2478

**Before**:
```python
elif not buy_alert_sent_successfully:
    should_create_order = False
    guard_reason = "ALERT_NOT_SENT"
```

**After**:
```python
# Trade execution is independent - proceed if signal exists and trade_enabled
# Alert sending is informational only, not a gate for trade execution
should_create_order = True
if buy_alert_sent_successfully:
    logger.info(f"🟢 BUY alert was sent successfully for {symbol}...")
else:
    logger.info(f"ℹ️ {symbol}: BUY alert not sent (may be throttled/disabled), "
                f"but proceeding with trade execution (trade is independent of alert).")
```

**Verification**: With `DIAG_FORCE_SIGNAL_BUY=1`, trade now shows:
- `TRADE decision=EXEC reason=EXEC_ORDER_PLACED blocked_by=none` (when trade_enabled=True)

### 2. Price Move Alert Channel ✅

**Implementation**: Added separate price move alert channel that triggers on significant price changes independent of buy/sell signals.

**Configuration**:
- `PRICE_MOVE_ALERT_PCT` (env var, default: 0.50%)
- `PRICE_MOVE_ALERT_COOLDOWN_SECONDS` (env var, default: 300s = 5 minutes)

**Features**:
- Separate throttle bucket using `strategy_key:PRICE_MOVE`
- Independent of signal alerts (doesn't interfere with trade execution)
- Triggers when `abs(price_change_pct) >= PRICE_MOVE_ALERT_PCT`
- DIAG trace: `PRICE_MOVE decision=... reason=...` line in diagnostic mode

**Location**: `backend/app/services/signal_monitor.py` lines ~1738-1800

**Throttle Reset**: Price move alerts use separate throttle bucket, so dashboard config changes reset signal alerts but price move alerts maintain their own cooldown independently.

## How to Verify Locally

### Run Regression Tests

```bash
cd backend
pytest tests/test_trade_alert_decoupling.py -v
```

This will verify:
- Trade execution is independent of alert sending
- Price move alerts trigger without buy/sell signals
- Price move alerts use separate throttle bucket
- Throttle reset works for price move alerts

### Run Diagnostic Scripts

**1. Standard diagnostic (shows signal conditions):**
```bash
cd backend
DIAG_SYMBOL=ETH_USDT python3 scripts/diag_throttle_reset.py
```

**2. Force signal to test trade path:**
```bash
cd backend
DIAG_SYMBOL=ETH_USDT DIAG_FORCE_SIGNAL_BUY=1 python3 scripts/diag_throttle_reset.py
```

Expected output:
- `TRADE decision=EXEC reason=EXEC_ORDER_PLACED blocked_by=none` (when trade_enabled=True)
- No `ALERT_NOT_SENT` blocking trade execution

### Price Move Alert Configuration

**Environment Variables:**
- `PRICE_MOVE_ALERT_PCT`: Price change threshold (default: 0.50%)
  - Example: `PRICE_MOVE_ALERT_PCT=1.0` for 1% threshold
- `PRICE_MOVE_ALERT_COOLDOWN_SECONDS`: Cooldown between alerts (default: 300s = 5 minutes)
  - Example: `PRICE_MOVE_ALERT_COOLDOWN_SECONDS=600` for 10 minutes

**Usage:**
```bash
cd backend
PRICE_MOVE_ALERT_PCT=0.25 PRICE_MOVE_ALERT_COOLDOWN_SECONDS=180 \
DIAG_SYMBOL=ETH_USDT python3 scripts/diag_throttle_reset.py
```

**Diagnostic Output:**
When price change exceeds threshold, you'll see:
```
PRICE_MOVE decision=EXEC reason=Price move threshold met symbol=ETH_USDT ...
```

### Verification Checklist

- [ ] Tests pass: `pytest tests/test_trade_alert_decoupling.py -v`
- [ ] Trade executes when `DIAG_FORCE_SIGNAL_BUY=1` and `trade_enabled=True`
- [ ] No `ALERT_NOT_SENT` blocking trade execution
- [ ] Price move alerts appear in DIAG trace when threshold met
- [ ] Price move alerts use `:PRICE_MOVE` throttle key (separate from signal alerts)

## Production Configuration

### Environment Variables

The price move alert feature is controlled by two environment variables:

- **`PRICE_MOVE_ALERT_PCT`**: Price change threshold percentage (default: `0.50`)
  - Triggers alert when `abs(price_change_pct) >= PRICE_MOVE_ALERT_PCT`
  - Example: `PRICE_MOVE_ALERT_PCT=1.0` for 1% threshold

- **`PRICE_MOVE_ALERT_COOLDOWN_SECONDS`**: Cooldown between alerts in seconds (default: `300` = 5 minutes)
  - Prevents alert spam on volatile markets
  - Example: `PRICE_MOVE_ALERT_COOLDOWN_SECONDS=600` for 10 minutes

### Docker Compose Configuration

The env vars are configured in `docker-compose.yml` for both:
- `backend-aws` service (API + signal monitor)
- `market-updater-aws` service (market data updater)

Default values are set via environment variable expansion:
```yaml
- PRICE_MOVE_ALERT_PCT=${PRICE_MOVE_ALERT_PCT:-0.50}
- PRICE_MOVE_ALERT_COOLDOWN_SECONDS=${PRICE_MOVE_ALERT_COOLDOWN_SECONDS:-300}
```

To override defaults, set in `.env.aws`:
```bash
PRICE_MOVE_ALERT_PCT=0.75
PRICE_MOVE_ALERT_COOLDOWN_SECONDS=600
```

### Production Log Line

When a price move alert is successfully sent, a single production log line is emitted:

```
PRICE_MOVE_ALERT_SENT symbol=ETH_USDT change_pct=0.63 price=$3400.00 threshold=0.50 cooldown_s=300
```

**Format**: Single line, easy to grep in AWS CloudWatch or log aggregation tools.

**When logged**: Only when alert is actually sent (not on SKIP decisions).

**Grep command**:
```bash
grep "PRICE_MOVE_ALERT_SENT" /path/to/logs
```

### AWS Verification Checklist

1. **Deploy**:
   ```bash
   # Ensure env vars are set in .env.aws or docker-compose.yml
   docker-compose --profile aws up -d backend-aws market-updater-aws
   ```

2. **Trigger a price move** (or wait for natural market movement):
   - Price change must exceed `PRICE_MOVE_ALERT_PCT` threshold
   - Must be outside cooldown period (`PRICE_MOVE_ALERT_COOLDOWN_SECONDS`)

3. **Verify in logs**:
   ```bash
   # In AWS CloudWatch or container logs
   docker logs market-updater-aws | grep "PRICE_MOVE_ALERT_SENT"
   # Or
   docker logs backend-aws | grep "PRICE_MOVE_ALERT_SENT"
   ```

4. **Expected output**:
   ```
   PRICE_MOVE_ALERT_SENT symbol=ETH_USDT change_pct=0.63 price=$3400.00 threshold=0.50 cooldown_s=300
   ```

5. **Verify Telegram alert received**:
   - Check Telegram channel for price move alert message
   - Format: "📊 Price Move Alert: {symbol}"

### Troubleshooting

- **No alerts appearing**: Check that `alert_enabled=True` for the watchlist item
- **Alerts too frequent**: Increase `PRICE_MOVE_ALERT_COOLDOWN_SECONDS`
- **Alerts not triggering**: Check that price change exceeds `PRICE_MOVE_ALERT_PCT` threshold
- **Logs not showing**: Ensure you're checking the correct container (backend-aws or market-updater-aws)

## Deployment Verification

### Pre-Deployment Checks

1. **Run regression tests**:
   ```bash
   cd backend
   pytest tests/test_trade_alert_decoupling.py -q
   ```
   Expected: `5 passed`

2. **Run diagnostic script**:
   ```bash
   cd backend
   DIAG_SYMBOL=ETH_USDT python3 scripts/diag_throttle_reset.py
   ```
   Verify:
   - TRADE decision lines appear (not blocked by ALERT_NOT_SENT)
   - PRICE_MOVE decision lines appear in DIAG mode when threshold met

3. **Verify docker-compose.yml**:
   - `backend-aws` service has `PRICE_MOVE_ALERT_PCT` and `PRICE_MOVE_ALERT_COOLDOWN_SECONDS`
   - `market-updater-aws` service has same env vars

### Deployment Steps

1. **Deploy to AWS** (standard deployment process):
   ```bash
   # Build and deploy as usual
   docker-compose --profile aws up -d --build backend-aws market-updater-aws
   ```

2. **Restart services** (to ensure env vars are picked up):
   ```bash
   docker-compose --profile aws restart backend-aws market-updater-aws
   ```

### Post-Deployment Verification

1. **Monitor logs** (tail and grep):
   ```bash
   # In AWS, tail logs from market-updater-aws (runs signal monitor loop)
   docker logs -f market-updater-aws | grep "PRICE_MOVE_ALERT_SENT"
   
   # Or from backend-aws
   docker logs -f backend-aws | grep "PRICE_MOVE_ALERT_SENT"
   ```

2. **Expected log format** (only when alert is actually sent):
   ```
   PRICE_MOVE_ALERT_SENT symbol=ETH_USDT change_pct=0.63 price=$3400.00 threshold=0.50 cooldown_s=300
   ```

3. **Verification checklist**:
   - [ ] Log appears only on real price moves (not on every evaluation)
   - [ ] Values printed match env thresholds (threshold=0.50, cooldown_s=300)
   - [ ] No extra noise logs (no logs on SKIP or cooldown)
   - [ ] Telegram alert received in channel
   - [ ] Price move alerts fire independently of buy/sell signals

### Deployment Record

**Pre-Deployment Verification** (Local):
- ✅ Regression tests pass: `5 passed`
- ✅ TRADE execution verified: Not blocked by alerts (`blocked_by=none` when trade_enabled=True)
- ✅ Docker-compose config verified: Env vars present in `backend-aws` and `market-updater-aws`

**Deployment Date**: _[To be filled after AWS deployment]_

**Deployment Steps**:
```bash
# From repo root
cd /path/to/automated-trading-platform
docker compose --profile aws up -d --build backend-aws market-updater-aws
docker compose --profile aws restart backend-aws market-updater-aws
```

**Status**: 
- [ ] Deployed to AWS
- [ ] PRICE_MOVE_ALERT_SENT observed in production logs
- [ ] Telegram alerts confirmed

**Production Log Evidence**:
```
# After deployment, run:
docker logs -f market-updater-aws | grep "PRICE_MOVE_ALERT_SENT"

# Expected format:
PRICE_MOVE_ALERT_SENT symbol=... change_pct=... price=$... threshold=... cooldown_s=...
```

**Observed Log Line**: _[Paste exact PRICE_MOVE_ALERT_SENT line from production logs]_

**Configuration Used**:
- `PRICE_MOVE_ALERT_PCT`: 0.50 (default)
- `PRICE_MOVE_ALERT_COOLDOWN_SECONDS`: 300 (default)

**Final Thresholds** (after any tuning):
- `PRICE_MOVE_ALERT_PCT`: _[Fill after deployment/verification]_
- `PRICE_MOVE_ALERT_COOLDOWN_SECONDS`: _[Fill after deployment/verification]_

**Tuning Applied**: _[None / Document any threshold adjustments]_

**Troubleshooting Notes** (if needed):
- If no alerts appear, temporarily set `PRICE_MOVE_ALERT_PCT=0.10` in `.env.aws` to force triggers
- Verify `alert_enabled=True` for watchlist items
- Check that market-updater-aws service is running and processing symbols

**Notes**: _[Any operational observations or tuning decisions]_

---

## AWS Deployment Handoff (Ready to Execute)

This section provides exact copy-paste ready commands to deploy and verify the PRICE_MOVE alert feature in AWS production. **All commands must be run on the AWS deployment server** where `docker compose --profile aws` is available.

### Deployment Commands

Execute these commands **in order** (copy-paste each command block):

#### a) Git sync

```bash
cd /path/to/automated-trading-platform
git pull
git log -1 --oneline
```

#### b) Optional env overrides

**Optional**: Check if `.env.aws` has overrides (defaults from docker-compose.yml are 0.50 and 300):

```bash
cd /path/to/automated-trading-platform
cat .env.aws | grep -E "PRICE_MOVE_ALERT_PCT|PRICE_MOVE_ALERT_COOLDOWN_SECONDS" || true
```

**Note**: If no overrides are found, defaults from docker-compose.yml are used (PRICE_MOVE_ALERT_PCT=0.50, PRICE_MOVE_ALERT_COOLDOWN_SECONDS=300). To override, add these lines to `.env.aws`:
```
PRICE_MOVE_ALERT_PCT=0.50
PRICE_MOVE_ALERT_COOLDOWN_SECONDS=300
```

#### c) Deploy

```bash
cd /path/to/automated-trading-platform
docker compose --profile aws up -d --build backend-aws market-updater-aws
```

#### d) Restart

```bash
cd /path/to/automated-trading-platform
docker compose --profile aws restart backend-aws market-updater-aws
```

#### e) Status

Verify both services are running:

```bash
cd /path/to/automated-trading-platform
docker compose --profile aws ps
```

**Required**: Both `backend-aws` and `market-updater-aws` must show status `Up`. If either service shows a different status, deployment has failed.

#### f) Verification

Monitor logs for PRICE_MOVE alert dispatches:

```bash
cd /path/to/automated-trading-platform
docker logs -f market-updater-aws | grep "PRICE_MOVE_ALERT_SENT"
```

**Important**: This command will **block and wait** until a price move exceeds the threshold and an alert is dispatched. The command does not return until a matching log line appears.

### Success Proof

Deployment is successful **ONLY if** at least one `PRICE_MOVE_ALERT_SENT` log line appears in production logs. If no such log line appears, deployment has failed.

The log line must match this exact format:
```
PRICE_MOVE_ALERT_SENT symbol=ETH_USDT change_pct=0.63 price=$3400.00 threshold=0.50 cooldown_s=300
```

This log line confirms:
- The PRICE_MOVE alert feature is active
- Alerts are being dispatched when price moves exceed the threshold
- The production logging is working correctly

### If no PRICE_MOVE alerts appear

If no `PRICE_MOVE_ALERT_SENT` log lines appear in production logs (after running step f) and waiting), follow these steps:

1. **Temporarily lower threshold to 0.10 in `.env.aws`**:
   Edit `.env.aws` and add or update this line:
   ```
   PRICE_MOVE_ALERT_PCT=0.10
   ```

2. **Re-deploy and restart services**:
   ```bash
   cd /path/to/automated-trading-platform
   docker compose --profile aws up -d backend-aws market-updater-aws
   cd /path/to/automated-trading-platform
   docker compose --profile aws restart backend-aws market-updater-aws
   ```

3. **Re-check logs** (this command will wait/block until an alert is dispatched):
   ```bash
   cd /path/to/automated-trading-platform
   docker logs -f market-updater-aws | grep "PRICE_MOVE_ALERT_SENT"
   ```

4. **Inspect last 200 log lines for diagnostics**:
   ```bash
   cd /path/to/automated-trading-platform
   docker logs --tail 200 market-updater-aws
   ```
   
   Verify the following in the logs:
   - Service is running and processing symbols
   - No exceptions in Telegram sending
   - Signal monitor loop is active
   - Watchlist items have `alert_enabled=True`

### Deployment Checklist

Before marking deployment as complete, you must verify all of the following (all items must be checked):

- [ ] Tests passed locally: `pytest tests/test_trade_alert_decoupling.py -q` (must show `5 passed`)
- [ ] Env vars verified in docker-compose.yml: Both `backend-aws` and `market-updater-aws` services must have `PRICE_MOVE_ALERT_PCT` and `PRICE_MOVE_ALERT_COOLDOWN_SECONDS` environment variables
- [ ] Services deployed: `docker compose --profile aws up -d --build` command completed with exit code 0
- [ ] Services restarted: `docker compose --profile aws restart` command completed with exit code 0
- [ ] PRICE_MOVE_ALERT_SENT observed: At least one log line matching the exact format in Success Proof section appears in production logs (this is the binary success criterion)
- [ ] Deployment record completed: All fields below are filled in with actual values (not placeholders)

### Deployment Record

Fill in this record **only after** successful deployment and verification. **Do not fill this record until** all checklist items are completed and at least one PRICE_MOVE_ALERT_SENT log line has been observed in production logs:

**Deployment date**: _[YYYY-MM-DD HH:MM:SS UTC]_

**Deployed by**: _[Name/username]_

**PRICE_MOVE_ALERT_PCT**: _[0.50 / or override value if different]_

**PRICE_MOVE_ALERT_COOLDOWN_SECONDS**: _[300 / or override value if different]_

**Proof log line** (paste exact line from production logs):
```
_[Paste exact PRICE_MOVE_ALERT_SENT line from production logs here]_
```

Status: Deployment handoff verified and ready for execution.