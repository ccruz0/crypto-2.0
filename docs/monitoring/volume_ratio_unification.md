# Volume Ratio Unification

**Date:** 2025-11-29  
**Status:** ✅ IMPLEMENTED

## Problem
The Volume column in the Watchlist and the strategy tooltip were showing different volume ratio values for the same coin at the same time. For example:
- Volume column: `6.8x`
- Tooltip: `Volume ratio 0.00x < 0.5x`

This discrepancy caused confusion because users couldn't understand why the strategy was blocking signals when the Volume column showed high volume.

## Root Cause
The Volume column and tooltip were using different sources for volume ratio calculation:
1. **Volume column**: Used various fallback sources (coin.volume_ratio, signal.volume_ratio, calculated from volume_24h, etc.)
2. **Tooltip**: Calculated `volumeRatio = volume / avgVolume` from signal/coin data, but used different volume sources than the strategy engine
3. **Strategy engine**: Calculated `volume_ratio = current_volume / avg_volume` using `current_volume` (last period) and `avg_volume` (moving average)

These different sources could produce different ratios even for the same coin at the same time.

## Solution

### Canonical Definition
**Strategy Volume Ratio** = `current_volume / avg_volume`
- `current_volume`: Volume from the last period (hourly)
- `avg_volume`: Moving average volume over N periods
- `volume_avg_periods`: Number of periods used for avg_volume calculation (currently **5 periods**)

This is the same calculation used by the strategy engine to decide whether volume conditions for BUY/SELL are met.

The period count is defined by the constant `VOLUME_AVG_PERIODS = 5` in `backend/app/services/trading_signals.py`, which matches the period used in `calculate_volume_index()`.

### Implementation

#### Backend (`routes_market.py`)
1. Extract `volume_ratio` from `calculate_trading_signals()` result (line 339 in `trading_signals.py`)
2. Use this strategy `volume_ratio` as the canonical value in the coin object
3. Fallback to recalculating only if strategy didn't provide it (e.g., on error)

**Key change:**
```python
# Extract strategy volume_ratio - this is the canonical volume ratio used by the strategy
strategy_volume_ratio = signals.get("volume_ratio")  # From calculate_trading_signals

# Use strategy volume_ratio as the canonical value
volume_ratio_value = strategy_volume_ratio
if volume_ratio_value is None:
    # Fallback: recalculate from current values
    ...
```

#### Frontend (`page.tsx`)

1. **Volume Column** (line 8387-8427):
   - **Priority 1**: Use `coin.volume_ratio` (strategy volume_ratio from backend)
   - **Priority 2-6**: Fallback to other sources only if strategy volume_ratio is not available

2. **Tooltip** (`buildSignalCriteriaTooltip`):
   - Added optional parameter `strategyVolumeRatio`
   - Uses strategy volume_ratio if provided, otherwise calculates from volume/avgVolume
   - Tooltip now shows: `"Ratio actual: X.XXx (mismo valor que columna Volume)"` to indicate it matches the Volume column

3. **Tooltip Call Site** (line 8565-8580):
   - Extracts `strategyVolumeRatio = coin.volume_ratio ?? signalEntry?.volume_ratio`
   - Passes it to `buildSignalCriteriaTooltip` as the canonical value

## Backend Fields

### Coin Object (from `/api/market/top-coins-data`)
```json
{
  "instrument_name": "NIR_USDT",
  "volume_ratio": 0.56,  // CANONICAL: Strategy volume ratio (current_volume / avg_volume)
  "current_volume": 1234567.89,  // Last period volume
  "avg_volume": 2200000.0,  // Moving average volume
  "strategy_state": {
    "decision": "WAIT",
    "reasons": {
      "buy_volume_ok": false  // Based on volume_ratio >= minVolumeRatio
    }
  }
}
```

### Signals Object (from `/api/signals`)
```json
{
  "symbol": "NIR_USDT",
  "volume_ratio": 0.56,  // Strategy volume ratio (same as coin.volume_ratio)
  "current_volume": 1234567.89,
  "avg_volume": 2200000.0
}
```

## UI Elements Using Strategy Volume Ratio

1. **Volume Column** (Watchlist table)
   - Displays: `X.Xx` (e.g., `0.6x`, `1.2x`, `6.8x`)
   - Source: `coin.volume_ratio` (strategy volume_ratio)

2. **Strategy Tooltip** (Signals column hover)
   - Shows: `"Ratio actual: X.XXx (mismo valor que columna Volume)"`
   - Shows: `"Promedio (N períodos): Y"` where N is the period count (e.g., "Promedio (5 períodos)")
   - Source: `coin.volume_ratio` passed as `strategyVolumeRatio` parameter
   - Period count: `coin.volume_avg_periods` (default: 5)
   - Condition check: Uses same ratio to evaluate `>= minVolumeRatio`

3. **Strategy Decision** (BUY/SELL/WAIT)
   - Uses: `volume_ratio >= minVolumeRatio` (from strategy rules)
   - Source: Same `volume_ratio` calculation in `calculate_trading_signals()`

## Interpretation

- **volume_ratio < 0.5x**: Low volume, insufficient market reaction (blocks BUY signals)
- **volume_ratio >= 0.5x**: Meets minimum threshold (allows BUY signals if other conditions met)
- **volume_ratio >= 1.0x**: Volume above average (stronger signal)
- **volume_ratio >= 2.0x**: High volume, significant market reaction

The `minVolumeRatio` threshold is configurable per strategy preset and risk mode (default: 0.5x).

## Verification

To verify the fix is working:

1. **Check Volume Column**: Should show a value like `0.6x`, `1.2x`, etc.
2. **Hover Strategy Tooltip**: Should show the same ratio value
3. **Check Strategy Decision**: If volume_ratio < minVolumeRatio, tooltip should show `✗` and explain why

Example:
- Volume column: `0.3x`
- Tooltip: `"Ratio actual: 0.30x (mismo valor que columna Volume)"` and `"Volume ≥ 0.5x promedio ✗"`
- Strategy: `WAIT` with reason `buy_volume_ok: false`

All three should be consistent.

## Files Changed

- `backend/app/api/routes_market.py`: Extract and use strategy volume_ratio
- `frontend/src/app/page.tsx`: 
  - Volume column: Prioritize `coin.volume_ratio`
  - Tooltip: Accept and use `strategyVolumeRatio` parameter
  - Tooltip call site: Pass `coin.volume_ratio` to tooltip function

## Notes

- The strategy volume_ratio is calculated in `calculate_trading_signals()` using `current_volume / avg_volume`
- Both `current_volume` and `avg_volume` come from `MarketData` table (updated by market_updater service)
- If volume data is unavailable, the strategy assumes volume is OK (doesn't block signals)
- The Volume column and tooltip will always show the same value for the same coin at the same time

