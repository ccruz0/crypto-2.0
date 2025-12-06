# Alert and Test Button Flow Documentation

## Current Implementation (Before Refactor)

### Frontend (page.tsx)

#### Single Alert Button
- **Location**: Lines 8341-8403
- **Function**: Toggles `alert_enabled` for a coin
- **Handler**: Calls `updateWatchlistAlert(symbol, newAlertStatus)`
- **State**: Tracked in `coinAlertStatus` state object (localStorage persisted)
- **Visual**: Shows "ALERT YES" (blue) or "ALERT NO" (gray)

#### Test Button  
- **Location**: Lines 8404-8460
- **Function**: Simulates a BUY alert for testing
- **Handler**: Calls `simulateAlert(symbol, 'BUY', forceOrder=true, amountUSD)`
- **Behavior**: 
  - Always simulates BUY signal
  - Forces order creation if Trade=YES and amountUSD > 0
  - Sends Telegram alert
  - Creates order with TP/SL if conditions met

### Backend API Endpoints

#### `/api/dashboard/{symbol}/alert` (PUT)
- **File**: `routes_dashboard.py`
- **Function**: Updates `alert_enabled` field for a watchlist item
- **Payload**: `{ "alert_enabled": true/false }`

#### `/api/test/simulate-alert` (POST)
- **File**: `routes_test.py` (lines 155-448)
- **Function**: Simulates BUY or SELL alert
- **Payload**: 
  ```json
  {
    "symbol": "ETH_USDT",
    "signal_type": "BUY" or "SELL",
    "force_order": true/false
  }
  ```
- **Behavior**:
  - For BUY: Sends Telegram alert, creates order if `trade_enabled=true` and `trade_amount_usd > 0`
  - For SELL: Sends Telegram alert only (no order creation)

### Order Creation with TP/SL

#### For BUY Orders
- Uses `create_sl_tp_for_order()` helper
- Calculates SL/TP based on strategy (ATR, risk/reward ratio)
- Creates STOP_LOSS and TAKE_PROFIT orders linked to main order

#### For SELL Orders
- Currently: Only alerts, no order creation
- TP/SL logic exists but not used for SELL in simulate-alert

## Target Implementation (After Refactor)

### Frontend Changes
1. **Replace single Alert button with two buttons**:
   - Buy Alert button
   - Sell Alert button
   - Both can be active independently

2. **State management**:
   - Track `buy_alert_enabled` and `sell_alert_enabled` separately
   - Store in localStorage for persistence

3. **Test button updates**:
   - Check both `buy_alert_enabled` and `sell_alert_enabled`
   - Trigger both alerts/orders if both enabled
   - Execute sequentially: Buy first, then Sell

### Backend Changes
1. **New endpoints or extend existing**:
   - `/api/dashboard/{symbol}/buy-alert` (PUT)
   - `/api/dashboard/{symbol}/sell-alert` (PUT)
   - Or extend `/api/dashboard/{symbol}/alert` with `direction` param

2. **Database schema** (if needed):
   - Add `buy_alert_enabled` and `sell_alert_enabled` columns
   - Or use single `alert_enabled` with new `alert_type` enum
   - **Decision**: Keep `alert_enabled` as master switch, add `buy_alert_enabled` and `sell_alert_enabled` for granularity

3. **Order creation**:
   - Buy orders: Create BUY order with TP (SELL side) and SL (SELL side)
   - Sell orders: Create SELL order with TP (BUY side) and SL (BUY side)

### Telegram Messages
- Distinguish BUY ALERT vs SELL ALERT
- Include source: "TEST" vs "LIVE ALERT"
- Show order details if Trade=YES and quantity > 0

