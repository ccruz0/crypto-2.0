# Order Cancellation Telegram Notifications

## Requirement

**Any order that is cancelled should trigger a Telegram notification.**

This document describes all order cancellation scenarios and their associated Telegram notification behavior.

---

## Quick Reference

| # | Scenario | Notification | Location | Trigger |
|---|----------|--------------|----------|---------|
| 1 | OCO Sibling Cancellation (Automatic) | ✅ **SENT** | `exchange_sync.py:_cancel_oco_sibling()` | When one SL/TP is filled, sibling auto-cancelled |
| 2 | Orphaned Order Cancellation | ✅ **SENT** | `routes_orders.py:POST /orders/find-orphaned` | Manual cleanup of orphaned SL/TP orders |
| 3 | Already-Cancelled OCO Sibling | ✅ **SENT** | `exchange_sync.py:_notify_already_cancelled_sl_tp()` | SL/TP executed, sibling already cancelled by exchange |
| 4 | Manual Order Cancellation via API | ✅ **SENT** | `routes_orders.py:POST /orders/cancel` | Manual cancellation via REST API |
| 5 | Cancel SL/TP Orders via API | ✅ **SENT** (Batched) | `routes_orders.py:POST /orders/cancel-sl-tp/{symbol}` | Bulk cancellation of SL/TP for symbol |
| 6 | Orders Marked as CANCELLED During Sync | ✅ **SENT** (Batched) | `exchange_sync.py:sync_open_orders()` | Orders not found in exchange open orders |
| 7 | REJECTED TP Orders Auto-Cancellation | ✅ **SENT** | `exchange_sync.py:sync_open_orders()` | REJECTED TP orders auto-cancelled by system |

**Status:** ✅ **All 7 scenarios send Telegram notifications**

---

## Cancellation Scenarios

### 1. OCO Sibling Cancellation (Automatic)

**Location:** `backend/app/services/exchange_sync.py:_cancel_oco_sibling()`

**Description:** When one SL/TP order is filled, the sibling (opposite SL/TP) is automatically cancelled as part of the One-Cancels-Other (OCO) logic.

**Notification:** ✅ **SENT**

- Detailed notification includes:
  - Symbol, order types, roles
  - Filled order details (price, quantity, time)
  - Cancelled order details (price, quantity, time)
  - Profit/loss calculation if applicable
  - OCO Group ID
  - Reason: OCO automatic cancellation

**Example Notification:**
```
🔄 OCO: Order Cancelled

📊 Symbol: BTC_USDT
🔗 OCO Group ID: 12345

✅ Filled Order:
   🎯 Type: STOP_LIMIT
   📋 Role: STOP_LOSS
   💵 Price: $50000.00
   📦 Quantity: 0.00100000
   ⏰ Time: 2025-01-27 10:30:00 UTC

❌ Cancelled Order:
   🎯 Type: TAKE_PROFIT_LIMIT
   📋 Role: TAKE_PROFIT
   💵 Price: $55000.00
   📦 Quantity: 0.00100000
   ⏰ Cancelled: 2025-01-27 10:30:01 UTC

💡 Reason: One-Cancels-Other (OCO) - When one protection order is filled, the other is automatically cancelled to prevent double execution.
```

---

### 2. Orphaned Order Cancellation

**Location:** `backend/app/api/routes_orders.py:POST /orders/find-orphaned`

**Description:** When orphaned SL/TP orders are detected (orders that should have been cancelled but weren't) and are cleaned up.

**Notification:** ✅ **SENT**

- Notification includes:
  - Symbol
  - Order role (SL/TP)
  - Order ID
  - Price and quantity (if available)
  - Reason: Orphaned order detected

**Example Notification:**
```
🗑️ ORPHANED ORDER DELETED

📊 Symbol: BTC_USDT
🛑 Type: STOP_LOSS
📋 Order ID: 1234567890
💵 Price: $50000.00
📦 Quantity: 0.00100000

💡 Reason: Orphaned order detected
✅ Order has been cancelled and removed.
```

---

### 3. Already-Cancelled OCO Sibling Notification

**Location:** `backend/app/services/exchange_sync.py:_notify_already_cancelled_sl_tp()`

**Description:** When a SL/TP order is executed and the sibling was already cancelled by Crypto.com OCO (before our system detected it).

**Notification:** ✅ **SENT**

- Notification includes:
  - Symbol
  - Executed order details
  - Already-cancelled order details
  - Profit/loss calculation if applicable
  - Reason: Already cancelled by Crypto.com OCO

---

### 4. Manual Order Cancellation via API

**Location:** `backend/app/api/routes_orders.py:POST /orders/cancel`

**Description:** When an order is manually cancelled via the REST API endpoint.

**Notification:** ✅ **SENT**

- Notification includes:
  - Symbol (if order exists in DB)
  - Side (BUY/SELL)
  - Order type and role
  - Order ID
  - Price and quantity (if available)
  - Reason: Manual cancellation via API

**Example Notification:**
```
❌ ORDER CANCELLED

📊 Symbol: BTC_USDT
🔄 Side: BUY
🎯 Type: LIMIT
📋 Order ID: 1234567890
💵 Price: $50000.00
📦 Quantity: 0.00100000

💡 Reason: Manual cancellation via API
```

---

### 5. Cancel SL/TP Orders via API

**Location:** `backend/app/api/routes_orders.py:POST /orders/cancel-sl-tp/{symbol}`

**Description:** When SL/TP orders are cancelled via the dedicated endpoint for a specific symbol.

**Notification:** ✅ **SENT**

- Single order: Detailed notification with all order details
- Multiple orders: Batched notification listing all cancelled orders (up to 10, with count if more)
- Notification includes:
  - Symbol
  - Order roles/types
  - Order IDs
  - Side (BUY/SELL)
  - Reason: Manual cancellation via API

**Example Notification (Multiple Orders):**
```
❌ SL/TP ORDERS CANCELLED

📊 Symbol: BTC_USDT
📋 3 orders have been cancelled:

1. 🛑 STOP_LOSS - SELL
   ID: 1234567890

2. 🚀 TAKE_PROFIT - SELL
   ID: 1234567891

3. 🛑 STOP_LOSS - SELL
   ID: 1234567892

💡 Reason: Manual cancellation via API
```

---

### 6. Orders Marked as CANCELLED During Sync

**Location:** `backend/app/services/exchange_sync.py:sync_open_orders()`

**Description:** When orders are not found in the exchange's open orders list during sync, the system MUST resolve the actual final state before marking as CANCELLED.

**⚠️ CRITICAL: "Not Found in Open Orders" ≠ "Canceled"**

**Process:**
1. Order missing from exchange open orders
2. System queries exchange order history to determine actual final state
3. System queries trade history if order history shows FILLED
4. Only after confirmation from exchange history is the order marked as CANCELLED or EXECUTED
5. Notification sent only after final state is confirmed

**Notification:** ✅ **SENT** (Batched) - Only after confirmation

- Single order: Detailed notification with status source
- Multiple orders: Batched notification listing all cancelled orders (up to 10, with count if more)
- Notification includes:
  - Symbol
  - Order type and role
  - Side (BUY/SELL)
  - Order ID
  - Price and quantity (if available)
  - Status source: order_history or trade_history
  - Reason: Order confirmed as CANCELLED via exchange history (not just "missing from open orders")

**Example Notification (Single Order):**
```
❌ ORDER CANCELLED (Sync)

📊 Symbol: BTC_USDT
🔄 Side: BUY
🎯 Type: LIMIT
📋 Order ID: 1234567890
💵 Price: $50000.00
📦 Quantity: 0.00100000
📋 Status Source: order_history

💡 Reason: Order confirmed as CANCELLED via exchange order history
```

---

### 7. REJECTED TP Orders Auto-Cancellation

**Location:** `backend/app/services/exchange_sync.py:sync_open_orders()`

**Description:** When REJECTED TP orders are automatically cancelled by the sync process (they should be removed automatically to prevent issues).

**Notification:** ✅ **SENT**

- Notification includes:
  - Symbol
  - Order ID
  - Order type
  - Price and quantity (if available)
  - Reason: TP order was REJECTED by exchange and automatically cancelled

**Example Notification:**
```
🗑️ REJECTED TP ORDER AUTO-CANCELLED

📊 Symbol: BTC_USDT
📋 Order ID: 1234567890
🎯 Type: TAKE_PROFIT_LIMIT
💵 Price: $55000.00
📦 Quantity: 0.00100000

💡 Reason: TP order was REJECTED by exchange and automatically cancelled to prevent issues
```

---

## Notification Format Standards

All cancellation notifications follow these standards:

1. **Emoji Usage:**
   - ❌ Generic cancellation
   - 🔄 OCO-related cancellation
   - 🗑️ Auto-cleanup/rejection cancellation
   - 🛑 Stop Loss orders
   - 🚀 Take Profit orders

2. **Information Included:**
   - Symbol (always)
   - Order ID (always)
   - Order type and role (when available)
   - Price and quantity (when available)
   - Reason for cancellation (always)

3. **Batching:**
   - Multiple cancellations from the same operation are batched into a single notification
   - Limit of 10 orders per notification for readability
   - If more than 10, shows count: "... and X more orders"

4. **Error Handling:**
   - Notification failures do not fail the cancellation operation
   - All notification errors are logged as warnings

---

## Implementation Details

### Code Locations

- **OCO Cancellation:** `backend/app/services/exchange_sync.py`
  - `_cancel_oco_sibling()` (line ~616)
  - `_send_oco_cancellation_notification()` (line ~462)
  - `_notify_already_cancelled_sl_tp()` (line ~1658)

- **API Endpoints:** `backend/app/api/routes_orders.py`
  - `POST /orders/cancel` (line ~159)
  - `POST /orders/cancel-sl-tp/{symbol}` (line ~190)
  - `POST /orders/find-orphaned` (line ~1257)

- **Sync Operations:** `backend/app/services/exchange_sync.py`
  - `sync_open_orders()` (line ~234)
  - REJECTED TP auto-cancellation (line ~363)

### Notification Service

All notifications use the `TelegramNotifier` service:
```python
from app.services.telegram_notifier import telegram_notifier

telegram_notifier.send_message(message, origin="AWS")
```

The `origin="AWS"` parameter ensures notifications are sent from the production environment.

---

## Testing

To verify notifications are working:

1. **Manual Cancellation:**
   - Cancel an order via API: `POST /orders/cancel`
   - Check Telegram channel for notification

2. **SL/TP Cancellation:**
   - Cancel SL/TP orders: `POST /orders/cancel-sl-tp/{symbol}`
   - Check Telegram channel for notification

3. **Sync Cancellation:**
   - Wait for sync cycle to run
   - If orders are cancelled during sync, check Telegram channel

4. **OCO Cancellation:**
   - Execute an SL or TP order
   - Check Telegram channel for sibling cancellation notification

### API Testing Examples

#### Test Manual Order Cancellation

```bash
# Cancel a single order by order_id
curl -X POST "http://your-api:8002/api/orders/cancel" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "exchange": "CRYPTO_COM",
    "order_id": "1234567890"
  }'

# Expected response:
# {
#   "ok": true,
#   "exchange": "CRYPTO_COM",
#   "canceled_id": "1234567890",
#   "result": {...}
# }
```

#### Test SL/TP Order Cancellation

```bash
# Cancel all SL/TP orders for a symbol
curl -X POST "http://your-api:8002/api/orders/cancel-sl-tp/BTC_USDT" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Expected response:
# {
#   "ok": true,
#   "symbol": "BTC_USDT",
#   "canceled_orders": [...]
# }
```

**Note:** After successful cancellation, check your Telegram channel for the notification message.

---

## Troubleshooting

### Notification Not Received?

If you cancelled an order but didn't receive a Telegram notification, follow these steps:

1. **Verify Telegram Configuration:**
   - Check that `TELEGRAM_BOT_TOKEN` is set correctly
   - Check that `TELEGRAM_CHAT_ID` is set correctly (usually negative number for channels)
   - Verify configuration: See [Telegram Setup Guide](../TELEGRAM_SETUP.md)
   - Ensure you're running on AWS environment (notifications only sent from AWS)

2. **Check Backend Logs:**
   ```bash
   # SSH into AWS instance
   ssh hilovivo-aws
   
   # Check backend logs for notification errors
   cd ~/automated-trading-platform
   docker compose --profile aws logs backend-aws | grep -i "notification\|telegram" | tail -50
   ```
   
   Look for:
   - ✅ `"Sent Telegram notification for cancelled order"` - Success
   - ⚠️ `"Failed to send Telegram notification"` - Check Telegram config
   - ❌ `"TelegramNotifier"` errors - Configuration issue

3. **Verify Order Was Actually Cancelled:**
   - Check the API response - should return `"ok": true`
   - Check exchange orders via API or exchange website
   - Check database: order status should be `CANCELLED`

4. **Check Telegram Bot Status:**
   - Ensure bot is added to the Telegram channel/group
   - Verify bot has permission to send messages
   - Test with a simple message from the bot

5. **Common Issues:**

   **Issue:** "Failed to send Telegram notification" in logs
   - **Solution:** Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are correct
   - Check network connectivity from AWS to Telegram API

   **Issue:** No notification for sync-based cancellations
   - **Solution:** Wait for next sync cycle (runs every 5 seconds)
   - Check if orders were actually cancelled (status = CANCELLED in DB)

   **Issue:** Notification sent but not visible in Telegram
   - **Solution:** Check if bot was removed from channel
   - Verify `TELEGRAM_CHAT_ID` matches the channel ID
   - Check if message was sent to wrong chat

6. **Enable Debug Logging:**
   ```bash
   # Set log level to DEBUG in docker-compose.yml or .env
   LOG_LEVEL=DEBUG
   
   # Restart backend
   docker compose --profile aws restart backend-aws
   
   # Monitor logs
   docker compose --profile aws logs -f backend-aws | grep -i telegram
   ```

### Verification Checklist

- [ ] `TELEGRAM_BOT_TOKEN` is set and valid
- [ ] `TELEGRAM_CHAT_ID` is set correctly (negative number for channels)
- [ ] Bot is added to Telegram channel/group
- [ ] Bot has permission to send messages
- [ ] Running on AWS environment (not local)
- [ ] Backend service is running and healthy
- [ ] No errors in backend logs related to Telegram
- [ ] Order cancellation API call returned success

---

## Related Documentation

- **[Telegram Setup Guide](../TELEGRAM_SETUP.md)** - How to configure Telegram notifications
- `OCO_IMPLEMENTATION_VS_DOCUMENTATION.md` - OCO system implementation details
- `OCO_CANCELLATION_CODE_REVIEW.md` - Code review of OCO cancellation logic
- `TP_CANCELLATION_FIX.md` - Fix for TP cancellation issues
- `ORDER_CANCELLATION_NOTIFICATION_AUDIT.md` - Audit of notification coverage

