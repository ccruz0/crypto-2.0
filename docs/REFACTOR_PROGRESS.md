# Alert System Refactor Progress

## ✅ Completed

1. **Backend Model Updates**
   - Added `buy_alert_enabled` and `sell_alert_enabled` columns to `WatchlistItem` model
   - Updated serialization functions to include new fields
   - Created new API endpoints:
     - `/watchlist/{symbol}/buy-alert` (PUT)
     - `/watchlist/{symbol}/sell-alert` (PUT)
   - Updated `/watchlist/{symbol}/alert` to maintain backward compatibility

2. **Frontend API Updates**
   - Added `updateBuyAlert()` and `updateSellAlert()` functions
   - Updated `WatchlistItem` interface to include new fields
   - Added state management for `coinBuyAlertStatus` and `coinSellAlertStatus`

3. **Frontend UI Updates**
   - Replaced single "ALERT" button with two buttons: "BUY ✅/❌" and "SELL ✅/❌"
   - Updated Test button to check both alert states and trigger both alerts if enabled
   - Updated localStorage persistence for buy/sell alert states
   - Updated loading logic to initialize states from database and localStorage

## 🔄 In Progress / Pending

1. **Database Migration** ⚠️ REQUIRED
   - Need to add `buy_alert_enabled` and `sell_alert_enabled` columns to PostgreSQL database
   - Migration script needed: `/tmp/add_buy_sell_alert_columns.py`

2. **Backend Test Endpoint Updates**
   - `/test/simulate-alert` currently only creates orders for BUY signals
   - Need to add SELL order creation logic (similar to BUY)
   - Need to create helper function `_create_sell_order()` in `signal_monitor.py`

3. **SELL Order Creation Logic**
   - Currently SELL signals only send alerts, no orders
   - Need to implement SELL order creation with TP/SL
   - TP/SL for SELL orders need to be inverted (TP is BUY side, SL is BUY side)

4. **Telegram Messages**
   - Update messages to distinguish BUY vs SELL alerts clearly
   - Include source (TEST vs LIVE ALERT) in messages
   - Show order details if Trade=YES and quantity > 0

5. **Testing**
   - Test buy alert button
   - Test sell alert button
   - Test Test button with both alerts enabled
   - Test order creation for both BUY and SELL
   - Verify TP/SL creation for both directions

## 📋 Next Steps

1. Create and run database migration script
2. Implement `_create_sell_order()` helper function
3. Update `/test/simulate-alert` endpoint to handle SELL orders
4. Update Telegram message formatting
5. Test end-to-end on AWS

## 🔗 Related Files

### Backend
- `backend/app/models/watchlist.py` - Model updated
- `backend/app/api/routes_market.py` - New endpoints added
- `backend/app/api/routes_dashboard.py` - Serialization updated
- `backend/app/api/routes_test.py` - Needs SELL order logic
- `backend/app/services/signal_monitor.py` - Needs `_create_sell_order()`

### Frontend
- `frontend/src/lib/api.ts` - API functions updated
- `frontend/src/app/page.tsx` - UI buttons replaced, Test button updated

