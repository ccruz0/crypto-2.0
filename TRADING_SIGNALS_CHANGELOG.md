# Trading Signals Implementation - Changelog

## Overview
Implemented advanced trading signals with dynamic TP/SL adjustment and momentum detection for the watchlist dashboard.

## Changes Summary

### Backend Changes

#### 1. New Service: `backend/app/services/trading_signals.py`
- **Purpose**: Advanced trading signals calculation with position-aware logic
- **Key Functions**:
  - `calculate_trading_signals()`: Main logic for BUY/SELL signals, TP/SL calculation, and dynamic adjustments
  - `get_signal_state_transition()`: Detects signal transitions for alerting

#### 2. Updated: `backend/app/api/routes_signals.py`
- **Changes**:
  - Extended `/signals` endpoint to use the new `trading_signals` service
  - Added volume analysis for momentum detection
  - Calculates MA10w (10-week moving average) for trend break detection
  - Returns enhanced signal data including TP, SL, boost flags, and rationale

### Frontend Changes

#### 1. New API Function: `frontend/src/lib/api.ts`
- **Added**: `getTradingSignals(symbol)` function
- **Type**: `TradingSignals` interface with signals, TP, SL, flags, and rationale

#### 2. Updated: `frontend/src/app/page.tsx`
- **Added State**: `signals` state to store trading signals for each symbol
- **Added Function**: `fetchSignals(symbol)` to load signals from backend
- **Updated useEffect**: Auto-fetch signals on initial load and every 10 seconds
- **Updated Watchlist Display**:
  - **Signals Column**: Shows BUY/SELL badges, TP boost (🚀), exhaustion (⚠️)
  - **Status Column**: Displays TP and SL values with color coding (green for TP, red for SL)

## Signal Logic Details

### Buy Signal Conditions
Triggers when ALL of the following are met:
- RSI < 40 (oversold condition)
- Price ≤ buy_target (if specified)
- MA50 > EMA10 (healthy uptrend)

When triggered:
- TP: +3% over entry price
- SL: Entry - (1.5 × ATR) or 3% default if ATR unavailable

### TP Boost Logic
Applies when momentum is detected:
- RSI between 65-75 AND volume > 1.2× average volume
- Boosted TP = max(+5% from entry, resistance_up) if resistance is higher
- Sets `tp_boosted` flag
- Adds rationale explaining boost reason

### Exhaustion Detection
Flags potential reversal risk:
- RSI > 70 AND volume < average volume
- Sets `exhaustion` flag
- Adds note about declining volume

### Sell Signal Conditions
Triggers when ANY of the following is true:
- RSI > 70 (overbought/reversal risk)
- Price breaks below MA10w with volume > 1.2× average (significant trend break)
  - Sets `ma10w_break` flag on significant break

## Data Requirements

### Required Data (for full functionality)
- `symbol`, `price`: Basic identification
- `rsi` (14-period): Buy/sell threshold checks
- `atr14`: Stop loss calculation
- `volume`, `avg_volume`: Momentum and exhaustion detection
- `ma50`, `ema10`: Trend confirmation
- `ma10w`: Long-term trend break detection
- `resistance_up`: TP boost ceiling
- `buy_target`: Entry price condition

### Handling Missing Data
- Missing RSI, ATR: System logs warning in rationale, uses fallback values
- Missing MA10w: Buy signals still function; sell signals omit trend break condition
- Missing resistance_up: TP boost uses +5% default
- All missing data is documented in the `rationale` array

## UI Components

### Signals Column
Displays interactive badges:
- **BUY** (green): Buy signal active
- **SELL** (red): Sell signal active
- **🚀** (yellow): TP boosted by momentum
- **⚠️** (gray): Exhaustion detected
- **-** (gray): No signal

### Status Column
Shows calculated levels:
- **TP**: Green text, format `$X.XX` (Take Profit level)
- **SL**: Red text, format `$X.XX` (Stop Loss level)

Both columns support hover tooltips explaining the signals.

## Alert System (Ready for Integration)

The `get_signal_state_transition()` function provides:
- **BUY_SIGNAL**: Transition from no buy to buy active
- **SELL_SIGNAL**: Transition from no sell to sell active
- **TP_BOOSTED**: Transition from normal TP to boosted TP

Alert format: `SYMBOL | BUY/SELL | TP=X | SL=X | notes`

## Performance Considerations

- Signals are fetched asynchronously per symbol to avoid blocking UI
- Updates refresh every 10 seconds along with other watchlist data
- Missing data is handled gracefully without breaking the UI
- Rationale array provides human-readable explanations for debugging

## Testing Recommendations

1. **Normal Operation**: Verify signals appear with data from Crypto.com API
2. **Partial Data**: Test with missing RSI, ATR, or MA values
3. **Edge Cases**: RSI exactly at thresholds (40, 70)
4. **Momentum Detection**: Volume spikes triggering TP boost
5. **Trend Break**: Price movements crossing MA10w with high volume
6. **Multiple Symbols**: All watchlist symbols load signals independently

## Future Enhancements

Potential improvements:
- Position tracking integration (last_buy_price from open positions)
- Real-time WebSocket signal updates
- Signal confidence scoring
- Historical signal performance tracking
- User-configurable RSI/volume thresholds
