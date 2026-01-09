# Order Lifecycle Guide - For Traders

**Purpose:** This guide explains how to interpret order statuses, Telegram notifications, and understand what actually happened with your trades.

---

## Order States

An order can be in one of these states:

| State | Meaning | What Happened |
|-------|---------|---------------|
| **CREATED** | Order placed successfully | Order was submitted to exchange and accepted, but not yet executed |
| **EXECUTED (FILLED)** | Order was filled | Order was executed - trade is complete |
| **CANCELED** | Order was canceled | Order was canceled - trade did NOT execute |

**⚠️ Important Rule:**
- If an order disappears from "Open Orders", it does NOT automatically mean it was canceled
- The system must check exchange history to confirm the actual final state
- Only after confirmation can we know if it was EXECUTED or CANCELED

---

## Order Roles

Orders can have different roles:

| Role | Purpose | When It Executes |
|------|---------|------------------|
| **PRIMARY** | Main buy/sell order from trading signal | When signal triggers and order is placed |
| **TAKE_PROFIT (TP)** | Profit-taking order | When price reaches profit target |
| **STOP_LOSS (SL)** | Risk management order | When price hits stop loss level |

- TP/SL orders are created after a primary order is filled
- When TP or SL executes, it closes the position
- Telegram messages indicate the order role when known

---

## Telegram Event Meanings

### ORDER_CREATED
- **Meaning:** Order was placed successfully on the exchange
- **What to know:** Order is pending, not yet executed
- **Action:** Wait for ORDER_EXECUTED or ORDER_CANCELED

### ORDER_EXECUTED
- **Meaning:** Order was filled - trade is complete
- **What to know:** This is the only confirmation that a trade actually happened
- **Action:** Check your position/balance - trade is done

### ORDER_CANCELED
- **Meaning:** Order was canceled - trade did NOT execute
- **What to know:** This means no trade happened
- **Action:** No position change - order was canceled before execution

### ORDER_FAILED
- **Meaning:** Order could not be placed (error during creation)
- **What to know:** Order never existed on exchange
- **Action:** Check error message for reason (insufficient balance, invalid parameters, etc.)

### SLTP_CREATED
- **Meaning:** Stop loss and take profit orders were placed
- **What to know:** Protection orders are now active
- **Action:** Monitor for SL/TP execution

### SLTP_FAILED
- **Meaning:** SL/TP orders could not be created
- **What to know:** Primary order may still be active, but without protection
- **Action:** Consider manual risk management

### TRADE_BLOCKED
- **Meaning:** Trade was prevented (cooldown, max orders, etc.)
- **What to know:** No order was placed
- **Action:** Check reason - may need to wait or adjust settings

---

## How to Read Alerts

### If you see ORDER_EXECUTED
✅ **Trade is done** - Order was filled, position changed

### If you see ORDER_CANCELED
❌ **Trade did NOT execute** - Order was canceled, no position change

### If you see only a signal (BUY/SELL alert)
⚠️ **Check for ORDER_CREATED** - Alert is sent first, then order is created
- If you see ORDER_CREATED after the alert → Order was placed automatically
- If you see TRADE_BLOCKED after the alert → Order was prevented (check reason)
- If you see neither → Order creation may be disabled (`trade_enabled=False`) or still processing

### If you see a sync message
🔄 **This is a reconciliation** - System is confirming order status from exchange
- Not a trading action
- Shows the system checking what actually happened
- Status source will be shown (order_history, trade_history)

---

## Sync Messages Explained

The system syncs with the exchange every 5 seconds to check order status.

**What sync does:**
1. Checks which orders are still open on the exchange
2. For orders missing from open orders:
   - Queries exchange order history to find actual final state
   - Queries trade history if order was filled
   - Updates status only after confirmation

**Sync message format:**
- Shows status source: `order_history`, `trade_history`, or `explicit_cancel`
- Example: "Order status confirmed via order_history: FILLED"
- Example: "Order status confirmed via trade_history: EXECUTED"

**Important:** Sync messages are informational - they show the system confirming what happened, not taking new actions.

---

## Order Creation Sequence

**Important:** Both BUY and SELL signals automatically create orders when:
- `trade_enabled=True` for the symbol
- `trade_amount_usd` is configured
- All guard checks pass (balance, limits, cooldowns, etc.)

### Complete Order Lifecycle Sequence

1. **Signal Detected** → Trading signal (BUY/SELL) is detected
2. **Alert Sent** → Telegram notification sent (if `alert_enabled=True`)
3. **Order Created** → Automatic order placed on exchange (if `trade_enabled=True`)
   - BUY orders: Buy base currency with quote currency (USDT)
   - SELL orders: Sell base currency for quote currency (USDT)
4. **Order Filled** → Order executed on exchange
5. **SL/TP Created** → Stop Loss and Take Profit orders created automatically
   - For BUY orders: SL/TP are SELL orders (sell at loss/profit)
   - For SELL orders: SL/TP are BUY orders (buy back at loss/profit)
6. **SL/TP Executed** → Protection order executes when price target is hit

**Note:** If order creation is blocked (guard checks fail), you'll see a `TRADE_BLOCKED` message with the reason.

## Common Scenarios

### Scenario 1: Signal → Alert → ORDER_CREATED → ORDER_EXECUTED → SLTP_CREATED
1. Trading signal detected (BUY/SELL alert sent to Telegram)
2. Order placed automatically (ORDER_CREATED)
3. Order filled (ORDER_EXECUTED)
4. SL/TP orders created (SLTP_CREATED)
**Result:** Trade completed successfully with protection orders active

### Scenario 2: Signal → Alert → ORDER_CREATED → ORDER_CANCELED
1. Trading signal detected (BUY/SELL alert sent to Telegram)
2. Order placed (ORDER_CREATED)
3. Order canceled (ORDER_CANCELED)
**Result:** No trade - order was canceled before execution, no SL/TP created

### Scenario 3: Signal → Alert → TRADE_BLOCKED
1. Trading signal detected (BUY/SELL alert sent to Telegram)
2. Trade blocked (TRADE_BLOCKED - reason shown)
**Result:** No order placed - trade was prevented (cooldown, max orders, insufficient balance, etc.)

### Scenario 4: Signal → Alert → ORDER_CREATED → ORDER_EXECUTED → SLTP_CREATED → ORDER_EXECUTED (TP)
1. Trading signal detected (BUY/SELL alert sent to Telegram)
2. Order placed (ORDER_CREATED)
3. Order filled (ORDER_EXECUTED)
4. SL/TP orders created (SLTP_CREATED)
5. Take profit executed (ORDER_EXECUTED for TP)
**Result:** Position opened and closed at profit target

### Scenario 5: Order disappears from Open Orders
1. Order was in Open Orders
2. Order disappears (not in Open Orders anymore)
3. System queries exchange history
4. Sync message shows confirmed status (EXECUTED or CANCELED)
**Result:** Final state confirmed - check sync message for actual status

---

## Troubleshooting

### "I saw a signal but no ORDER_CREATED"
- Check for TRADE_BLOCKED message - trade may have been blocked
- Check if trading is enabled for that symbol
- Check if max open orders limit was reached

### "I saw ORDER_CREATED but no ORDER_EXECUTED"
- Order may still be pending - check Open Orders tab
- Order may have been canceled - check for ORDER_CANCELED
- Wait for sync to confirm final state

### "Order disappeared from Open Orders but no notification"
- Wait for sync cycle (runs every 5 seconds)
- Check Executed Orders tab - order may have been filled
- Check for sync message showing confirmed status

### "I see ORDER_CANCELED but don't know why"
- Check cancel reason in notification
- Common reasons:
  - Manual cancellation
  - OCO sibling cancellation (SL/TP pair)
  - Order expired
  - Exchange rejection

---

## Quick Reference

| What You See | What It Means | Action |
|--------------|---------------|--------|
| ORDER_EXECUTED | Trade completed | ✅ Check position/balance |
| ORDER_CANCELED | Trade did not execute | ❌ No position change |
| ORDER_CREATED | Order placed, pending | ⏳ Wait for execution or cancel |
| TRADE_BLOCKED | Trade prevented | ⚠️ Check reason |
| SLTP_CREATED | Protection orders active | 🛡️ Monitor for SL/TP execution |
| Sync message | Status confirmation | ℹ️ Informational only |

---

## Related Documentation

- **[System Map](SYSTEM_MAP.md)** - Technical details of order lifecycle
- **[Order Cancellation Notifications](ORDER_CANCELLATION_NOTIFICATIONS.md)** - All cancellation scenarios
- **[Lifecycle Events](LIFECYCLE_EVENTS_COMPLETE.md)** - Event implementation details


