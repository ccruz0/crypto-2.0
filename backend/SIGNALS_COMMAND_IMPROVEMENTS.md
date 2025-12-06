# /signals Command Improvements

## Changes Made

### Enhanced Signal Display
The `/signals` command now shows comprehensive information about each trading signal:

### Information Displayed

1. **💰 Signal Price (Historical)**
   - Price when the signal was generated
   - From `TradeSignal.current_price`

2. **💵 Current Price**
   - Current market price of the coin
   - From `WatchlistItem.price` (updated by background services)

3. **📊 Price Change Comparison**
   - Percentage change: `((current - signal) / signal) × 100`
   - **🟢 Green** if price increased (potential profit)
   - **🔴 Red** if price decreased (potential loss)
   - **⚪ Neutral** if no change

4. **📊 Technical Parameters**
   - Shows the parameters that created the signal:
     - RSI (Relative Strength Index)
     - MA50 (50-period Moving Average)
     - EMA10 (10-period Exponential Moving Average)

5. **📦 Order Information**
   - **If order was placed:**
     - Order ID (first 12 characters)
     - Order status (ACTIVE, FILLED, etc.)
     - Order price
   - **If order was NOT placed:**
     - Reason: "waiting for signal confirmation", "pending", etc.
     - Status from signal

6. **🕐 Timestamp**
   - When the signal was last updated
   - Displayed in Asia/Singapore timezone

## Example Output

### Signal with Order Placed
```
🟢 *BTC_USDT* BUY
━━━━━━━━━━━━━━━━━━━━
💰 Signal Price: $98,500.00
💵 Current Price: $101,470.00 🟢
   Change: +3.01%
📊 RSI: 45.2 | MA50: $97,800.00 | EMA10: $99,200.00
📦 Order: dry_123456...
   Status: ACTIVE | Price: $98,750.00
🕐 2025-11-06 19:36:08
```

### Signal without Order (Pending)
```
🟢 *ETH_USDT* BUY
━━━━━━━━━━━━━━━━━━━━
💰 Signal Price: $3,320.00
💵 Current Price: $3,321.50 🟢
   Change: +0.05%
📊 RSI: 42.8 | MA50: $3,280.00 | EMA10: $3,310.00
⏸️ Order not placed yet (waiting for signal confirmation)
🕐 2025-11-06 19:36:08
```

### Signal with Price Drop
```
🟢 *SOL_USDT* BUY
━━━━━━━━━━━━━━━━━━━━
💰 Signal Price: $155.00
💵 Current Price: $152.30 🔴
   Change: -1.74%
📊 RSI: 38.5 | MA50: $150.00
⏸️ Order not placed yet (waiting for signal confirmation)
🕐 2025-11-06 18:22:15
```

## Code Changes

### Updated Function
- `send_signals_message()` in `telegram_commands.py`

### Key Improvements
1. Simplified to use only `TradeSignal` model (primary source)
2. Added price comparison logic with color indicators
3. Added technical parameters display
4. Enhanced order information with database lookup
5. Better status messages for orders not placed
6. Cleaner message formatting

## Data Sources

| Field | Source | Fallback |
|-------|--------|----------|
| Signal Price | `TradeSignal.current_price` | 0 |
| Current Price | `WatchlistItem.price` | Signal Price |
| RSI | `TradeSignal.rsi` | None |
| MA50 | `TradeSignal.ma50` | None |
| EMA10 | `TradeSignal.ema10` | None |
| Order ID | `TradeSignal.exchange_order_id` | None |
| Order Details | `ExchangeOrder` table | Status from signal |

## Benefits

1. **Transparency**: See exactly why a signal was generated
2. **Performance Tracking**: Know if you're in profit or loss
3. **Decision Making**: See technical indicators that triggered the signal
4. **Order Status**: Know if order was placed and its current status
5. **Historical Context**: Compare signal price vs current price

## Testing

Test the command:
```
/signals
```

Expected:
- List of recent BUY signals
- Each with signal price, current price, % change
- Technical parameters (RSI, MA50, EMA10)
- Order status or reason if not placed
- Clear visual indicators (🟢 for up, 🔴 for down)

## Files Modified
- `backend/app/services/telegram_commands.py`: Complete rewrite of `send_signals_message()`

