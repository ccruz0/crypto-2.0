# Strategy Logging Fix

**Date:** 2025-11-30  
**Issue:** DEBUG_STRATEGY_FINAL logs were not appearing in Docker logs  
**Status:** ✅ Fixed

## Root Cause

The enhanced logging markers (`STRATEGY_DEBUG_MARKER` and `DEBUG_STRATEGY_FINAL`) were added to `backend/app/services/trading_signals.py` but the container was using a cached build that didn't include these changes.

## Investigation

### Container Setup

- **Container Name:** `automated-trading-platform-backend-aws-1`
- **Service Name:** `backend-aws`
- **Mounts:** None (code is baked into image, not bind-mounted)
- **Runtime File Path:** `/app/app/services/trading_signals.py`

### Code Path Verification

```bash
# Container imports from:
docker exec automated-trading-platform-backend-aws-1 python3 -c \
  "from app.services import trading_signals; print(trading_signals.__file__)"
# Output: /app/app/services/trading_signals.py
```

### Canonical Implementation

**Single Implementation:** `backend/app/services/trading_signals.py`

- **Function:** `calculate_trading_signals()` (line 199)
- **Used by:**
  - `SignalMonitorService` (imports from `app.services.trading_signals`)
  - `/api/signals` endpoint (imports from `app.services.trading_signals`)
  - `/api/market` endpoint (imports from `app.services.trading_signals`)

**No duplicates found** - only one definition exists in the codebase.

## Solution

### 1. Added Logging Markers

**Entry Marker** (line ~219):
```python
logger.info(
    "STRATEGY_DEBUG_MARKER | symbol=%s | price=%s",
    symbol,
    price,
)
```

**Final Marker** (line ~673):
```python
logger.info(
    "DEBUG_STRATEGY_FINAL | symbol=%s | decision=%s | buy_signal=%s | "
    "buy_rsi_ok=%s | buy_volume_ok=%s | buy_ma_ok=%s | buy_target_ok=%s | buy_price_ok=%s",
    symbol,
    strategy_state.get("decision"),
    result.get("buy_signal"),
    strategy_reasons.get("buy_rsi_ok"),
    strategy_reasons.get("buy_volume_ok"),
    strategy_reasons.get("buy_ma_ok"),
    strategy_reasons.get("buy_target_ok"),
    strategy_reasons.get("buy_price_ok"),
)
```

### 2. Deployment Process

Since the container uses a built image (no bind mounts), the deployment requires:

```bash
# 1. Copy updated file to server
scp backend/app/services/trading_signals.py \
  hilovivo-aws:/home/ubuntu/automated-trading-platform/backend/app/services/

# 2. Rebuild backend image
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker compose build backend-aws'

# 3. Restart container
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker compose up -d backend-aws'
```

### 3. Verification

After deployment, verify logs appear:

```bash
# Check for entry markers
docker logs automated-trading-platform-backend-aws-1 --tail 1000 | \
  grep "STRATEGY_DEBUG_MARKER"

# Check for final markers
docker logs automated-trading-platform-backend-aws-1 --tail 1000 | \
  grep "DEBUG_STRATEGY_FINAL"
```

## Example Log Output

Once active, logs will appear like:

```
STRATEGY_DEBUG_MARKER | symbol=ALGO_USDT | price=0.1414
DEBUG_STRATEGY_FINAL | symbol=ALGO_USDT | decision=WAIT | buy_signal=False | buy_rsi_ok=True | buy_volume_ok=None | buy_ma_ok=True | buy_target_ok=True | buy_price_ok=True
```

Or for BUY signals:

```
STRATEGY_DEBUG_MARKER | symbol=ALGO_USDT | price=0.1414
DEBUG_STRATEGY_FINAL | symbol=ALGO_USDT | decision=BUY | buy_signal=True | buy_rsi_ok=True | buy_volume_ok=True | buy_ma_ok=True | buy_target_ok=True | buy_price_ok=True
```

## Files Changed

- `backend/app/services/trading_signals.py`:
  - Added `STRATEGY_DEBUG_MARKER` at function entry (line ~219)
  - Updated `DEBUG_STRATEGY_FINAL` format to match requirements (line ~673)

## Usage with Debug Script

The existing `debug_strategy.py` script will now find these logs:

```bash
bash scripts/debug_strategy_remote.sh ALGO_USDT 20
```

The script searches for `DEBUG_STRATEGY_FINAL` in Docker logs and will now successfully find and parse these entries.

