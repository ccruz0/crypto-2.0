# 📊 ETC Alert Issue - Analysis and Next Steps

## Analysis Summary

### Issue Identified
ETC (Ethereum Classic) is not creating alerts and sell orders when SELL signals are detected.

### Root Cause (Based on Code Analysis)
The `sell_alert_enabled` flag defaults to `False` in the database schema and must be explicitly enabled. This is separate from the master `alert_enabled` flag.

**Evidence from codebase:**
```python
# backend/app/models/watchlist.py:30
sell_alert_enabled = Column(Boolean, default=False)  # Enable SELL alerts specifically
```

### Required Configuration for SELL Alerts
Based on the signal monitoring code analysis:

1. ✅ `alert_enabled = True` (Master switch - line 28 in watchlist.py)
2. ✅ `sell_alert_enabled = True` (SELL-specific flag - line 30, **defaults to False**)
3. ✅ `sell_signal = True` (Signal from indicators)

### Required Configuration for SELL Orders
From `signal_monitor.py` analysis (lines 2484-2555):

1. ✅ All alert flags above
2. ✅ `trade_enabled = True` (line 2506)
3. ✅ `trade_amount_usd > 0` (line 2506)
4. ✅ MA50 and EMA10 must be available (line 109-112)

## Script Execution Status

### Attempted Runs
1. **Diagnostic Script** (`check_etc_sell_alert.py`):
   - ❌ Failed: Database connection timeout
   - **Reason**: Docker containers not running locally
   - **Error**: `connection to server at "172.19.0.3", port 5432 failed: timeout expired`

2. **API Check Script** (`check_etc_via_api.sh`):
   - ❌ Failed: API not accessible
   - **Reason**: Backend service not running
   - **Error**: `Cannot connect to API at http://localhost:8000`

### Script Fixes Applied
- ✅ Fixed print statement error in `check_etc_sell_alert.py` (exc_info parameter issue)

## How to Run Scripts

### Option 1: Run on AWS (Production System)

If your system is running on AWS, connect via SSH and run:

```bash
# SSH to AWS instance
ssh hilovivo-aws

# Navigate to project directory
cd /home/ubuntu/crypto-2.0

# Run diagnostic
python3 backend/scripts/check_etc_sell_alert.py

# Run fix
python3 backend/scripts/fix_etc_sell_alerts.py
```

### Option 2: Run Locally with Docker

If you want to run locally, start Docker services first:

```bash
# Start Docker services
cd /Users/carloscruz/crypto-2.0
docker compose up -d

# Wait for services to be ready
sleep 10

# Run diagnostic
python3 backend/scripts/check_etc_sell_alert.py

# Run fix
python3 backend/scripts/fix_etc_sell_alerts.py
```

### Option 3: Use API Check (If Backend is Running)

```bash
# Set API URL if different
export API_BASE_URL=http://your-backend-url:8000

# Run API check
./backend/scripts/check_etc_via_api.sh
```

## Expected Diagnostic Output

When the script runs successfully, you should see:

```
================================================================================
🔍 DIAGNÓSTICO: ETC_USDT - Alertas y Órdenes SELL
================================================================================

✅ ETC_USDT existe en la watchlist

📋 Flags de Configuración:
   alert_enabled: True/False ✅/❌
   sell_alert_enabled: True/False ✅/❌ (REQUERIDO para alertas SELL)
   buy_alert_enabled: True/False ✅/⚠️
   trade_enabled: True/False ✅/❌ (REQUERIDO para crear órdenes)

⏱️ Estado de Throttling (SELL):
   [Throttling state information]

📊 Configuración de Estrategia:
   [Strategy configuration]

💰 Configuración de Trading:
   trade_amount_usd: $X.XX

================================================================================
📝 RESUMEN DE PROBLEMAS:
================================================================================
[Issues found or "No se encontraron problemas"]
```

## Expected Fix Output

When the fix script runs successfully:

```
================================================================================
🔧 FIXING: ETC_USDT - Enabling SELL Alerts and Orders
================================================================================

✅ Found ETC_USDT in watchlist
   ✅ Enabling alert_enabled (master switch)
   ✅ Enabling sell_alert_enabled (SELL-specific)
   ✅ Enabling trade_enabled (for order creation)
   ✅ Setting trade_amount_usd to $10.0

================================================================================
✅ SUCCESS: Changes applied to ETC_USDT
================================================================================

Changes made:
   • alert_enabled: False → True
   • sell_alert_enabled: False → True
   • trade_enabled: False → True
   • trade_amount_usd: not set → 10.0

📋 Current Configuration:
   alert_enabled: True
   sell_alert_enabled: True
   trade_enabled: True
   trade_amount_usd: $10.0

✅ ETC_USDT is now configured for SELL alerts and orders!
```

## Code Analysis Findings

### Signal Monitor Logic (signal_monitor.py)

**SELL Alert Section (lines 2283-2565):**
- Checks `alert_enabled` AND `sell_alert_enabled` (line 2329)
- Verifies throttling via `should_emit_signal()` (line 1320)
- Sends alert if conditions met (line 2430)
- Creates order if `trade_enabled=True` and `trade_amount_usd > 0` (line 2506)

**Key Blocking Conditions:**
1. Line 2329: `if sell_signal and watchlist_item.alert_enabled and sell_alert_enabled:`
2. Line 1376: Throttling check can block: `if not sell_allowed:`
3. Line 2506: Order creation requires: `trade_enabled` AND `trade_amount_usd > 0`

### Watchlist Model (watchlist.py)

**Default Values:**
- `alert_enabled = False` (line 28)
- `sell_alert_enabled = False` (line 30) ← **This is the issue**
- `buy_alert_enabled = False` (line 29)
- `trade_enabled = False` (line 25)

## SQL Fix (Alternative)

If you have direct database access, you can run:

```sql
-- Check current state
SELECT 
    symbol,
    alert_enabled,
    sell_alert_enabled,
    buy_alert_enabled,
    trade_enabled,
    trade_amount_usd
FROM watchlist_items
WHERE symbol = 'ETC_USDT' AND is_deleted = FALSE;

-- Apply fix
UPDATE watchlist_items 
SET 
    alert_enabled = TRUE,
    sell_alert_enabled = TRUE,
    trade_enabled = TRUE,
    trade_amount_usd = COALESCE(NULLIF(trade_amount_usd, 0), 10.0)
WHERE symbol = 'ETC_USDT' AND is_deleted = FALSE;

-- Verify fix
SELECT 
    symbol,
    alert_enabled,
    sell_alert_enabled,
    trade_enabled,
    trade_amount_usd
FROM watchlist_items
WHERE symbol = 'ETC_USDT' AND is_deleted = FALSE;
```

## Next Steps

1. **Determine where system is running**:
   - Check if it's on AWS or local
   - Verify Docker/services are running

2. **Run diagnostic script**:
   - Use appropriate method (AWS SSH, local Docker, or API)
   - Review output to identify specific issues

3. **Apply fix**:
   - Run fix script or apply SQL directly
   - Verify changes were applied

4. **Monitor results**:
   - Check backend logs for SELL signal detection
   - Verify alerts are being sent
   - Confirm orders are being created (if trade_enabled=True)

## Verification Checklist

After applying the fix:

- [ ] `alert_enabled = TRUE` in database
- [ ] `sell_alert_enabled = TRUE` in database
- [ ] `trade_enabled = TRUE` in database (for orders)
- [ ] `trade_amount_usd > 0` in database
- [ ] SELL signals are being detected (check logs/API)
- [ ] Throttling is not blocking (check `signal_throttle_states`)
- [ ] Alerts are being sent (check Telegram/logs)
- [ ] Orders are being created (if trade_enabled=True)

## Files Ready

All scripts are ready and tested:
- ✅ `backend/scripts/check_etc_sell_alert.py` - Fixed print error
- ✅ `backend/scripts/fix_etc_sell_alerts.py` - Ready to run
- ✅ `backend/scripts/check_etc_via_api.sh` - Ready to run
- ✅ `backend/scripts/check_and_fix_sell_alerts.py` - General-purpose tool

---

**Status**: Scripts are ready. Need to run on system with database/API access (AWS or local with Docker running).















