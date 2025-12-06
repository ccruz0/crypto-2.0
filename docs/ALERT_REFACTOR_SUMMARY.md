# Alert System Refactor - Complete Summary

## ✅ Implementation Complete

### 1. Database Schema
- **Model Updated**: `backend/app/models/watchlist.py`
  - Added `buy_alert_enabled` (Boolean, default=False)
  - Added `sell_alert_enabled` (Boolean, default=False)
  - `alert_enabled` remains as master switch

- **Migration Script**: `/tmp/add_buy_sell_alert_columns.py`
  - Adds columns to PostgreSQL database
  - Migrates existing `alert_enabled=True` to both `buy_alert_enabled=True` and `sell_alert_enabled=True`

### 2. Backend API Endpoints
- **New Endpoints** (`backend/app/api/routes_market.py`):
  - `PUT /watchlist/{symbol}/buy-alert` - Toggle buy alerts
  - `PUT /watchlist/{symbol}/sell-alert` - Toggle sell alerts
  - `PUT /watchlist/{symbol}/alert` - Legacy endpoint (maintains backward compatibility)

- **Updated Endpoints**:
  - `POST /test/simulate-alert` - Now creates orders for both BUY and SELL signals
  - Serialization functions updated to include new fields

### 3. Backend Services
- **New Function**: `_create_sell_order()` in `backend/app/services/signal_monitor.py`
  - Creates SELL MARKET orders
  - Validates base currency balance
  - Creates TP/SL orders automatically (TP is BUY side, SL is BUY side for SELL orders)
  - Handles margin trading
  - Saves to database (order_history_db and ExchangeOrder)

- **Updated Function**: `_create_buy_order()` 
  - No changes needed (already working)

- **TP/SL Creation**: 
  - Works for both BUY and SELL orders
  - Uses `exchange_sync._create_sl_tp_for_filled_order()` which handles both directions

### 4. Telegram Notifications
- **Updated**: `send_buy_signal()` - Now includes `source` parameter ("LIVE ALERT" or "TEST")
- **New**: `send_sell_signal()` - Similar to `send_buy_signal()` but for SELL alerts
- **Messages**: Clearly distinguish BUY vs SELL, include source indicator

### 5. Frontend
- **UI Changes** (`frontend/src/app/page.tsx`):
  - Replaced single "ALERT YES/NO" button with two buttons:
    - "BUY ✅/❌" (green when enabled, gray when disabled)
    - "SELL ✅/❌" (red when enabled, gray when disabled)
  - Both buttons can be active independently

- **State Management**:
  - `coinBuyAlertStatus` - Tracks buy alert state per coin
  - `coinSellAlertStatus` - Tracks sell alert state per coin
  - Both persisted in localStorage

- **Test Button**:
  - Checks both `buyAlertEnabled` and `sellAlertEnabled`
  - If buy enabled → triggers buy alert + order (if Trade=YES and quantity > 0)
  - If sell enabled → triggers sell alert + order (if Trade=YES and quantity > 0)
  - If both enabled → executes both sequentially

- **API Functions** (`frontend/src/lib/api.ts`):
  - `updateBuyAlert(symbol, buyAlertEnabled)` - New
  - `updateSellAlert(symbol, sellAlertEnabled)` - New
  - `updateWatchlistAlert()` - Legacy (maintained for backward compatibility)

## 📋 Behavior Summary

### Buy Alert Button
- **When Enabled**: 
  - Sends BUY alerts to Telegram (if `alert_enabled=True` master switch is on)
  - Creates BUY orders with TP/SL if `Trade=YES` and `trade_amount_usd > 0`
  - TP is SELL side (sell at profit)
  - SL is SELL side (sell at loss)

### Sell Alert Button
- **When Enabled**:
  - Sends SELL alerts to Telegram (if `alert_enabled=True` master switch is on)
  - Creates SELL orders with TP/SL if `Trade=YES` and `trade_amount_usd > 0`
  - TP is BUY side (buy back at profit)
  - SL is BUY side (buy back at loss)

### Test Button
- **Behavior**:
  - Checks `buyAlertEnabled` and `sellAlertEnabled` states
  - If buy enabled → sends buy alert + creates buy order (if conditions met)
  - If sell enabled → sends sell alert + creates sell order (if conditions met)
  - If both enabled → executes both (buy first, then sell)
  - All alerts marked with "🧪 TEST MODE" in Telegram

### Order Creation Conditions
Both BUY and SELL orders are created only when:
1. Alert button is enabled (`buy_alert_enabled=True` or `sell_alert_enabled=True`)
2. `Trade=YES` (`trade_enabled=True`)
3. `trade_amount_usd > 0`
4. Sufficient balance (USD/USDT for BUY, base currency for SELL)

### TP/SL Attachment
- **For BUY Orders**:
  - TP: SELL order at profit price (above entry)
  - SL: SELL order at loss price (below entry)

- **For SELL Orders**:
  - TP: BUY order at profit price (below entry - price dropped)
  - SL: BUY order at loss price (above entry - price rose)

## 🚀 Deployment Steps

### 1. Run Database Migration
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose exec -T db python3 -c \"$(cat /tmp/add_buy_sell_alert_columns.py)\""
```

Or execute the migration script directly on AWS:
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose exec db psql -U trader -d atp -c \"
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='watchlist_items' AND column_name='buy_alert_enabled') THEN
        ALTER TABLE watchlist_items ADD COLUMN buy_alert_enabled BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='watchlist_items' AND column_name='sell_alert_enabled') THEN
        ALTER TABLE watchlist_items ADD COLUMN sell_alert_enabled BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    UPDATE watchlist_items SET buy_alert_enabled = alert_enabled, sell_alert_enabled = alert_enabled WHERE alert_enabled = TRUE;
END
\$\$;
\""
```

### 2. Sync Code to AWS
```bash
cd /Users/carloscruz/automated-trading-platform
git add .
git commit -m "feat: Split alert button into Buy Alert and Sell Alert with full order creation support"
git push

ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && git pull"
```

### 3. Rebuild Backend
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose build backend && docker compose up -d backend"
```

### 4. Rebuild Frontend
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker compose build frontend && docker compose up -d frontend"
```

### 5. Verify
- Open dashboard: `https://hilovivo.com`
- Check that Buy Alert and Sell Alert buttons appear
- Test Buy Alert button (should toggle and save)
- Test Sell Alert button (should toggle and save)
- Test Test button with both alerts enabled
- Verify Telegram messages show correct source (TEST vs LIVE ALERT)

## 📝 Files Changed

### Backend
- `backend/app/models/watchlist.py` - Added columns
- `backend/app/api/routes_market.py` - New endpoints
- `backend/app/api/routes_dashboard.py` - Updated serialization
- `backend/app/api/routes_test.py` - SELL order creation
- `backend/app/services/signal_monitor.py` - `_create_sell_order()` function
- `backend/app/services/telegram_notifier.py` - `send_sell_signal()` and source parameter

### Frontend
- `frontend/src/app/page.tsx` - UI buttons and Test button logic
- `frontend/src/lib/api.ts` - New API functions

### Documentation
- `docs/ALERT_FLOW.md` - Current vs target implementation
- `docs/REFACTOR_PROGRESS.md` - Progress tracking
- `docs/ALERT_REFACTOR_SUMMARY.md` - This file

## ⚠️ Important Notes

1. **Backward Compatibility**: The legacy `alert_enabled` endpoint still works and sets both buy/sell alerts to match
2. **Master Switch**: `alert_enabled` acts as a master switch - if False, no alerts are sent regardless of buy/sell settings
3. **Database Migration**: Must be run before deploying to avoid errors
4. **Column Safety**: All code uses `hasattr()` and `getattr()` to handle missing columns gracefully

