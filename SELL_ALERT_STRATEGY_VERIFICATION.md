# Sell Alert Conditions - Strategy Verification

## Actual Strategies for BTC_USDT and LDO_USD

From `trading_config.json`:

- **BTC_USDT**: `"swing"` → **Swing-Conservative** (default)
- **LDO_USD**: `"scalp-aggressive"`

## Corrected Sell Alert Conditions

### For BTC_USDT (Swing-Conservative)

**Sell alerts will be sent when ALL of these are met:**

1. ✅ **RSI > 70** (BTC_USDT: 90.33 ✅ **MET**)
2. ✅ **`sell_alert_enabled=True`** ✅ (just enabled)
3. ✅ **`alert_enabled=True`** ✅ (already enabled)
4. ❓ **MA reversal REQUIRED**: 
   - MA50 < EMA10 (with >= 0.5% difference) **OR** price < MA10w
   - **This is likely the blocker!** If MA50 >= EMA10, sell alert won't trigger
5. ❓ **Volume confirmation**: `volume_ratio >= 0.5x`
6. ❓ **Throttle check**: Passes cooldown and price change requirements

### For LDO_USD (Scalp-Aggressive)

**Sell alerts will be sent when ALL of these are met:**

1. ✅ **RSI > 65** (LDO_USD: 81.30 ✅ **MET**)
2. ✅ **`sell_alert_enabled=True`** ✅ (just enabled)
3. ✅ **`alert_enabled=True`** ✅ (already enabled)
4. ✅ **MA reversal NOT REQUIRED**: 
   - Scalp-Aggressive has `ma50: false` in maChecks
   - `trend_reversal = True` always (no MA check needed)
5. ❓ **Volume confirmation**: `volume_ratio >= 0.3x` (overridden to 0.30 for LDO_USD)
6. ❓ **Throttle check**: Passes cooldown and price change requirements

## Key Differences

| Symbol | Strategy | RSI Threshold | MA Reversal Required? | Volume Min |
|--------|----------|---------------|----------------------|------------|
| **BTC_USDT** | Swing-Conservative | **70** | ✅ **YES** | 0.5x |
| **LDO_USD** | Scalp-Aggressive | **65** | ❌ **NO** | 0.3x |

## Why Alerts Might Not Be Triggering

### BTC_USDT (RSI 90.33)
- ✅ RSI condition: **MET** (90.33 > 70)
- ❓ **MA reversal**: **MUST CHECK** - This is the most likely blocker
  - Need: MA50 < EMA10 (>= 0.5% diff) OR price < MA10w
  - If MA50 >= EMA10, alert won't trigger even with RSI 90.33
- ❓ Volume: Need >= 0.5x
- ❓ Throttle: Must pass

### LDO_USD (RSI 81.30)
- ✅ RSI condition: **MET** (81.30 > 65)
- ✅ MA reversal: **NOT REQUIRED** (Scalp-Aggressive)
- ❓ Volume: Need >= 0.3x (lower threshold due to override)
- ❓ Throttle: Must pass

## Conclusion

**My original statement was partially incorrect:**

❌ **Wrong**: "RSI > 70" for all symbols
✅ **Correct**: RSI threshold varies by strategy:
- BTC_USDT: RSI > 70 ✅
- LDO_USD: RSI > 65 ✅

❌ **Wrong**: "MA reversal always required"
✅ **Correct**: MA reversal requirement varies:
- BTC_USDT (Swing): **REQUIRED** ❓ (likely blocker)
- LDO_USD (Scalp-Aggressive): **NOT REQUIRED** ✅

## Most Likely Blockers

1. **BTC_USDT**: MA reversal condition (MA50 >= EMA10)
2. **LDO_USD**: Volume confirmation (< 0.3x) or throttle

Run the diagnostic script to verify:
```bash
python3 backend/scripts/diagnose_sell_alerts.py
```
