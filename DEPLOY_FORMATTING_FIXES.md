# Deploy Formatting Fixes

## Summary

This deployment includes formatting compliance fixes that ensure all order prices and quantities follow the rules in `docs/trading/crypto_com_order_formatting.md`.

## Changes Being Deployed

### Files Modified
- `backend/app/services/brokers/crypto_com_trade.py`
  - Added `normalize_price()` helper function
  - Fixed `place_limit_order()` - correct rounding directions
  - Fixed `place_stop_loss_order()` - correct rounding directions
  - Fixed `place_take_profit_order()` - correct rounding directions
  - Fixed error retry logic rounding
  - Fixed linting errors
  - Updated telegram imports

- `backend/app/services/tp_sl_order_creator.py`
  - Removed `round()` usage
  - Removed ROUND_HALF_UP usage
  - Removed pre-formatting

- `backend/app/services/exchange_sync.py`
  - Removed `round()` usage
  - Removed ROUND_HALF_UP usage
  - Removed pre-formatting

## Deployment Options

### Option 1: Deploy via SSM (Recommended)

```bash
# Make sure changes are committed and pushed first
git add backend/app/services/brokers/crypto_com_trade.py backend/app/services/tp_sl_order_creator.py backend/app/services/exchange_sync.py
git commit -m "Fix: Formatting compliance - Implement normalize_price() and correct rounding directions

- Added normalize_price() helper function following docs/trading/crypto_com_order_formatting.md
- Fixed rounding directions: BUY=ROUND_DOWN, SELL/TP=ROUND_UP, SL=ROUND_DOWN
- Preserved trailing zeros in all formatting
- Removed round() usage from formatting code
- Fixed linting errors
- Updated telegram_service imports to telegram_notifier

All order placement now complies with formatting documentation rules."

git push origin main

# Then deploy
bash deploy_formatting_fixes.sh
```

### Option 2: Quick Deploy (If Already Committed)

```bash
bash deploy_formatting_fixes.sh
```

### Option 3: Manual Steps

```bash
# On AWS EC2
cd /home/ubuntu/automated-trading-platform
git pull origin main
docker compose --profile aws build backend-aws
docker compose --profile aws restart backend-aws
sleep 15
docker compose --profile aws ps backend-aws
curl -sS -m 10 http://127.0.0.1:8002/health
```

## What This Fixes

✅ **Rule 1**: Uses Decimal (not binary floats)
✅ **Rule 2**: Quantizes to tick_size/step_size
✅ **Rule 3**: Correct rounding directions by order type
✅ **Rule 4**: Preserves trailing zeros
✅ **Rule 5**: Fetches instrument metadata

## Verification

After deployment, verify:

```bash
# Check container is running
docker compose --profile aws ps backend-aws

# Check health
curl -sS http://127.0.0.1:8002/health

# Check logs for formatting
docker logs --tail 100 $(docker compose --profile aws ps -q backend-aws) | grep -E "(NORMALIZE_PRICE|normalize_price)" | head -20

# Check for errors
docker logs --tail 200 $(docker compose --profile aws ps -q backend-aws) | grep -i error | tail -20
```

## Expected Results

- ✅ Backend restarts successfully
- ✅ Health check passes
- ✅ Orders use correct formatting (no "Invalid quantity format" or "Invalid price" errors)
- ✅ Logs show normalize_price() being used
- ✅ No formatting-related errors in logs

## Risk Assessment

**Risk Level**: LOW
- Changes are backward compatible
- Uses helper functions (centralized logic)
- Extensive logging preserved
- Error retry logic still functional

## Rollback (if needed)

```bash
cd /home/ubuntu/automated-trading-platform
git checkout HEAD~1 -- backend/app/services/brokers/crypto_com_trade.py backend/app/services/tp_sl_order_creator.py backend/app/services/exchange_sync.py
docker compose --profile aws build backend-aws
docker compose --profile aws restart backend-aws
sleep 15
curl -sS http://127.0.0.1:8002/health
```

---

**Status**: ✅ Ready to Deploy
**Impact**: High (ensures correct order formatting, prevents exchange rejections)
