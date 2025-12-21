# Sell Alert Conditions by Strategy

## Summary

**My previous statement was partially correct but incomplete.** The sell alert conditions **DO vary by strategy**. Here's the accurate breakdown:

## Strategy-Specific Sell Conditions

### 1. RSI Sell Threshold (varies by strategy)

**NOT always 70!** The threshold depends on the strategy:

| Strategy | Risk Approach | RSI Sell Threshold |
|----------|---------------|-------------------|
| **Swing** | Conservative | **70** |
| **Swing** | Aggressive | **68** |
| **Intraday** | Conservative | **70** |
| **Intraday** | Aggressive | **65** |
| **Scalp** | Conservative | **70** |
| **Scalp** | Aggressive | **65** |

### 2. MA Reversal Requirement (varies by strategy)

**NOT always required!** It depends on the strategy's `maChecks` configuration:

| Strategy | MA50 Check Required? | MA Reversal Needed? |
|----------|---------------------|-------------------|
| **Swing** | ✅ Yes (`ma50: True`) | ✅ **REQUIRED** (MA50 < EMA10 OR price < MA10w) |
| **Intraday** | ✅ Yes (`ma50: True`) | ✅ **REQUIRED** (MA50 < EMA10 OR price < MA10w) |
| **Scalp** | ❌ No (`ma50: False`) | ❌ **NOT REQUIRED** (trend_reversal = True always) |

### 3. Volume Confirmation (same for all)

- **All strategies**: `volume_ratio >= 0.5x` (default `minVolumeRatio: 0.5`)
- **Critical**: If volume data is missing or zero, sell signals are **BLOCKED**

## For BTC_USDT and LDO_USD

Based on the dashboard showing "Swing-" (partially visible), they likely use:

**Most Likely: Swing-Conservative**
- ✅ RSI > **70** (BTC_USDT: 90.33 ✅, LDO_USD: 81.30 ✅)
- ✅ **MA reversal REQUIRED**: MA50 < EMA10 (with >= 0.5% difference) OR price < MA10w
- ✅ Volume >= 0.5x
- ✅ Throttle check passes

**If Swing-Aggressive:**
- ✅ RSI > **68** (BTC_USDT: 90.33 ✅, LDO_USD: 81.30 ✅)
- ✅ **MA reversal REQUIRED**: MA50 < EMA10 OR price < MA10w
- ✅ Volume >= 0.5x
- ✅ Throttle check passes

## What This Means

For **BTC_USDT (RSI 90.33)** and **LDO_USD (RSI 81.30)**:

1. ✅ **RSI condition**: Met (both > 70, and even > 68 if aggressive)
2. ❓ **MA reversal**: **MUST be checked** - This is likely the blocker!
   - Need MA50 < EMA10 (with >= 0.5% difference) OR price < MA10w
   - If MA50 >= EMA10, sell alert will **NOT trigger** even with high RSI
3. ❓ **Volume**: Must be >= 0.5x average
4. ❓ **Throttle**: Must pass cooldown/price change checks

## Corrected Statement

**Sell alerts will be sent when ALL of these are met:**

1. ✅ **RSI > strategy-specific threshold** (70 for Swing-Conservative, 68 for Swing-Aggressive, 65 for Intraday-Aggressive, etc.)
2. ✅ **`sell_alert_enabled=True`** ✅ (just enabled)
3. ✅ **`alert_enabled=True`** ✅ (already enabled)
4. ❓ **MA reversal** (if strategy requires it):
   - **Swing/Intraday**: REQUIRED - MA50 < EMA10 (>= 0.5% diff) OR price < MA10w
   - **Scalp**: NOT REQUIRED
5. ❓ **Volume confirmation**: `volume_ratio >= 0.5x`
6. ❓ **Throttle check**: Passes cooldown and price change requirements

## Next Steps to Verify

To check why BTC_USDT and LDO_USD aren't triggering sell alerts:

1. **Check their actual strategy** (Swing-Conservative vs Swing-Aggressive)
2. **Verify MA reversal condition**: Check if MA50 < EMA10 for these symbols
3. **Check volume data**: Verify volume_ratio >= 0.5x
4. **Check throttle status**: See if alerts are being throttled

The diagnostic script (`diagnose_sell_alerts.py`) will show exactly which condition is blocking the alerts.




