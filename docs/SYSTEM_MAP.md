# System Map - Trading Platform Architecture

**Date:** 2026-01-02  
**Purpose:** Single source of truth for system architecture and data flow

---

## Overview

This document describes the complete data flow and order lifecycle for the automated trading platform, from signal detection through order execution and event logging.

---

## 1. System Components

### 1.1 Core Services

| Service | File | Responsibility |
|---------|------|----------------|
| **SignalMonitorService** | `backend/app/services/signal_monitor.py` | Main orchestrator: monitors signals, creates orders, manages lifecycle |
| **ExchangeSyncService** | `backend/app/services/exchange_sync.py` | Syncs exchange data, creates SL/TP orders, handles order execution events |
| **SignalThrottle** | `backend/app/services/signal_throttle.py` | Manages alert/trade throttling based on price change and cooldown |
| **StrategyProfiles** | `backend/app/services/strategy_profiles.py` | Resolves strategy type (swing/intraday/scalp) and risk approach (conservative/aggressive) |
| **TradingSignals** | `backend/app/services/trading_signals.py` | Calculates BUY/SELL signals based on technical indicators |
| **TelegramNotifier** | `backend/app/services/telegram_notifier.py` | Sends alerts and notifications to Telegram |
| **CryptoComTrade** | `backend/app/services/brokers/crypto_com_trade.py` | Exchange API client for order placement |

### 1.2 Data Models

| Model | File | Purpose |
|-------|------|---------|
| **WatchlistItem** | `backend/app/models/watchlist.py` | Per-coin configuration (alerts, trading, strategy) |
| **ExchangeOrder** | `backend/app/models/exchange_order.py` | All orders (primary, SL, TP) |
| **SignalThrottleState** | `backend/app/models/signal_throttle.py` | Throttle state per symbol/strategy/side |
| **TradeSignal** | `backend/app/models/trade_signal.py` | Signal history and status |

### 1.3 API Endpoints

| Endpoint | File | Purpose |
|----------|------|---------|
| `/api/monitoring/summary` | `backend/app/api/routes_monitoring.py` | Monitoring tab data |
| `/api/monitoring/telegram-messages` | `backend/app/api/routes_monitoring.py` | Throttle/audit tab data |
| `/api/open-orders` | `backend/app/api/routes_orders.py` | Open Orders tab data |
| `/api/executed-orders` | `backend/app/api/routes_orders.py` | Executed Orders tab data |

---

## 2. Order Lifecycle (Source of Truth)

### 2.0 Order Lifecycle States (Critical Understanding)

**An order can transition to these final states:**

| State | Meaning | Confirmation Source |
|-------|---------|-------------------|
| **CREATED** | Order placed successfully, awaiting execution | Exchange API response + Database |
| **EXECUTED (FILLED)** | Order was filled/executed | Exchange order history or trade history |
| **CANCELED** | Order was explicitly canceled, expired, or rejected | Exchange order history or explicit cancel API response |

**⚠️ CRITICAL RULE:**
- **"Order not found in Open Orders" ≠ "Order canceled"**
- When an order disappears from Open Orders, the system MUST resolve the real final state using exchange history
- Only after confirmation from exchange history can it be classified as EXECUTED or CANCELED
- Never assume missing from open orders means canceled

**Order Role Types:**
- **PRIMARY**: The main buy/sell order placed from a trading signal
- **TAKE_PROFIT (TP)**: Profit-taking order linked to a primary order
- **STOP_LOSS (SL)**: Risk management order linked to a primary order
- TP/SL execution can close a position
- Telegram messages indicate order role when known

### 2.1 Sync Logic (Critical Clarification)

**Service:** `ExchangeSyncService.sync_orders()` (runs every 5 seconds)

**Process:**
1. **Check Open Orders**: Fetches current open orders from exchange API
2. **Compare with Database**: Identifies orders in database that are not in exchange open orders
3. **Resolve Final State** (CRITICAL):
   - If order missing from open orders:
     - System MUST query exchange order history to determine actual final state
     - System MUST query trade history if order history shows FILLED
     - Only after confirmation can it be classified as EXECUTED or CANCELED
   - Never mark as CANCELED just because it's missing from open orders
4. **Update Database**: Updates order status based on confirmed final state
5. **Emit Events**: Emits ORDER_EXECUTED or ORDER_CANCELED only after confirmation

**Sync Message Semantics:**
- Sync messages must state the status source (open_orders, order_history, trade_history)
- Example: "Order status confirmed via order_history: FILLED"
- Example: "Order status confirmed via trade_history: EXECUTED"

### Phase 1: Continuous Monitoring
- **Service:** `SignalMonitorService._monitor_signals()`
- **Frequency:** Every 30 seconds (configurable via `monitor_interval`)
- **Action:** For each coin in watchlist:
  - Fetch market data (price, RSI, MAs, volume)
  - Calculate trading signals via `calculate_trading_signals()`
  - Determine strategy profile (swing/intraday/scalp + conservative/aggressive)

### Phase 2: Signal Detection
- **Service:** `SignalMonitorService._monitor_signals()`
- **Trigger:** `buy_signal=True` OR `sell_signal=True` from `calculate_trading_signals()`
- **Output:** Signal state (BUY/SELL/WAIT) with strategy decision

### Phase 3: Alerts (if enabled)
- **Service:** `SignalMonitorService._monitor_signals()`
- **Gate:** `alert_enabled=True` OR (`buy_alert_enabled=True` for BUY) OR (`sell_alert_enabled=True` for SELL)
- **Throttle Check:** `should_emit_signal()` checks:
  - Price change threshold (default 1.0%)
  - Cooldown period (fixed 60 seconds)
- **Actions if allowed:**
  - Emit alert to Telegram via `telegram_notifier.send_buy_alert()` or `send_sell_alert()`
  - Record event to throttle via `record_signal_event()` → `SignalThrottleState`
  - Log to monitoring UI
- **Actions if blocked:**
  - Log `TRADE_BLOCKED` with reason (SKIP_COOLDOWN_ACTIVE, SKIP_PRICE_CHANGE_INSUFFICIENT, etc.)
  - Record to throttle with `alert_decision=SKIP` and `alert_reason=<reason>`

### Phase 4: Trade Gate
- **Service:** `SignalMonitorService._monitor_signals()`
- **Gate Checks (in order):**
  1. `trade_enabled=True` (watchlist flag)
  2. `trade_amount_usd > 0` (valid trade amount)
  3. No signal → `SKIP_NO_SIGNAL`
  4. Max open orders check → `SKIP_MAX_OPEN_ORDERS` (max 3 per symbol)
  5. Cooldown check (same as alert throttle)
- **Actions if blocked:**
  - Log `TRADE_BLOCKED` event with gate name and reason
  - Record to throttle with `trade_decision=SKIP` and `trade_reason=<reason>`
  - **DO NOT** place order
- **Actions if allowed:**
  - Proceed to order placement

### Phase 5: Primary Order Placement
- **Service:** `SignalMonitorService._create_buy_order()` or `_create_sell_order()`
- **Order Type:** MARKET (for automatic orders)
- **Exchange:** Crypto.com via `trade_client.place_market_order()`
- **On Success:**
  - Save to `ExchangeOrder` (PostgreSQL) and `order_history_db` (SQLite)
  - Emit `ORDER_CREATED` event:
    - Telegram: `telegram_notifier.send_order_created()`
    - Throttle: Record to `SignalThrottleState` with `order_created=True`
    - Log: Structured log with order_id, symbol, side, price, quantity
- **On Failure:**
  - Emit `ORDER_FAILED` event:
    - Telegram: Error notification with details
    - Throttle: Record with `order_created=False` and error message
    - Log: Error log with full exception
  - **STOP** - do not proceed to SL/TP

### Phase 6: Post-Order Risk Orders (SL/TP)
- **Service:** `ExchangeSyncService._create_sl_tp_for_filled_order()`
- **Trigger:** After primary order is confirmed FILLED (immediate or via polling)
- **Timing:** 
  - For BUY orders: After fill confirmation (polling if needed)
  - For SELL orders: After fill confirmation
- **Process:**
  1. Poll for fill confirmation if not immediately filled (`_poll_order_fill_confirmation()`)
  2. Normalize quantity via `trade_client.normalize_quantity()`
  3. Calculate SL/TP prices from strategy (swing/intraday/scalp + conservative/aggressive)
  4. Create SL order via `trade_client.place_stop_loss_order()`
  5. Create TP order via `trade_client.place_take_profit_order()`
- **On Success:**
  - Emit `SLTP_CREATED` event:
    - Telegram: Success notification with SL and TP order IDs
    - Throttle: Record with `sltp_created=True` and order IDs
    - Log: Structured log with all order IDs and prices
- **On Failure:**
  - Emit `SLTP_FAILED` event:
    - Telegram: CRITICAL alert with error details
    - Throttle: Record with `sltp_created=False` and error message
    - Log: Error log with full exception
  - If `FAILSAFE_ON_SLTP_ERROR=True`: Send additional FAILSAFE alert with recommended actions

### Phase 7: Execution and Cancel Events (Sync Process)
- **Service:** `ExchangeSyncService.sync_orders()` (runs every 5 seconds)
- **Process:**
  1. Fetch open orders from exchange API
  2. Compare with database orders
  3. **For orders missing from open orders:**
     - Query exchange order history to determine actual final state
     - Query trade history if order history shows FILLED
     - **DO NOT** assume missing = canceled
  4. Update database with confirmed final state
  5. Emit events only after confirmation
- **On Execution (FILLED confirmed via order_history or trade_history):**
  - Emit `ORDER_EXECUTED` event:
    - Telegram: `telegram_notifier.send_executed_order()`
    - Throttle: Record with execution details
    - Log: Structured log with fill quantity, price, timestamps, status source
  - If SL/TP executed: Cancel sibling order (OCO behavior)
  - If primary order executed: Trigger SL/TP creation (if not already created)
- **On Cancel (CANCELLED confirmed via order_history or explicit cancel):**
  - Emit `ORDER_CANCELED` event:
    - Telegram: Cancel notification with status source
    - Throttle: Record with cancel reason and status source
    - Log: Structured log with cancel details and status source

### Phase 8: UI Truth
- **Open Orders Tab:**
  - Source: `/api/open-orders`
  - Data: All orders with status `NEW`, `ACTIVE`, `PARTIALLY_FILLED` (includes SL/TP)
  - Includes: Primary orders, SL orders, TP orders
- **Executed Orders Tab:**
  - Source: `/api/executed-orders`
  - Data: All orders with status `FILLED` OR `CANCELLED`
  - Includes: Executed orders AND canceled orders (including SL/TP)
- **Monitoring Tab:**
  - Source: `/api/monitoring/summary`
  - Data: Active alerts (from watchlist state), system health, recent signals
- **Throttle/Audit Tab:**
  - Source: `/api/monitoring/telegram-messages`
  - Data: All throttle events (alerts, blocks, orders, executions)

---

## 3. Coin & Strategy Configuration

### 3.1 Coin Tracking
- **Source:** `WatchlistItem` table
- **Key Fields:**
  - `symbol`: Exchange symbol (e.g., "BTC_USDT")
  - `exchange`: Exchange name (default: "CRYPTO_COM")
  - `alert_enabled`: Master alert switch
  - `buy_alert_enabled`: BUY alert switch
  - `sell_alert_enabled`: SELL alert switch
  - `trade_enabled`: Trading switch
  - `trade_amount_usd`: Trade amount in USD
  - `sl_tp_mode`: Risk approach ("conservative" or "aggressive")
  - `min_price_change_pct`: Price change threshold (overrides strategy default)

### 3.2 Strategy Resolution
- **Service:** `resolve_strategy_profile()` in `strategy_profiles.py`
- **Priority:**
  1. Watchlist `sl_tp_mode` (risk approach only)
  2. `trading_config.json` preset for symbol
  3. `trading_config.json` defaults
  4. Fallback: (SWING, CONSERVATIVE)
- **Strategy Types:**
  - `SWING`: Longer-term positions
  - `INTRADAY`: Day trading
  - `SCALP`: Quick scalps
- **Risk Approaches:**
  - `CONSERVATIVE`: Tighter SL, wider TP
  - `AGGRESSIVE`: Wider SL, tighter TP

### 3.3 Strategy Configuration File
- **Location:** `backend/trading_config.json`
- **Structure:**
```json
{
  "coins": {
    "BTC_USDT": {
      "preset": "swing-conservative"
    }
  },
  "defaults": {
    "preset": "swing-conservative"
  }
}
```

---

## 4. Decision Gates

### 4.1 Alert Gates
| Gate Name | Check | Block Reason | Location |
|-----------|-------|--------------|----------|
| `SKIP_DISABLED_ALERT` | `alert_enabled=False` AND (`buy_alert_enabled=False` for BUY OR `sell_alert_enabled=False` for SELL) | Alerts disabled | `signal_monitor.py:1595` |
| `SKIP_COOLDOWN_ACTIVE` | Time since last same-side alert < cooldown (60s) | Cooldown active | `signal_throttle.py:should_emit_signal()` |
| `SKIP_PRICE_CHANGE_INSUFFICIENT` | Price change < threshold (default 1.0%) | Price change too small | `signal_throttle.py:should_emit_signal()` |
| `SKIP_NO_SIGNAL` | No BUY/SELL signal detected | No signal | `signal_monitor.py:1546` |

### 4.2 Trade Gates
| Gate Name | Check | Block Reason | Location |
|-----------|-------|--------------|----------|
| `SKIP_DISABLED_TRADE` | `trade_enabled=False` | Trading disabled | `signal_monitor.py:3782` |
| `SKIP_INVALID_TRADE_AMOUNT` | `trade_amount_usd <= 0` | Invalid trade amount | `signal_monitor.py:3782` |
| `SKIP_NO_SIGNAL` | No BUY/SELL signal | No signal | `signal_monitor.py:3782` |
| `SKIP_MAX_OPEN_ORDERS` | Open BUY orders >= 3 | Max orders reached | `signal_monitor.py:3782` |
| `SKIP_COOLDOWN_ACTIVE` | Same as alert cooldown | Cooldown active | `signal_monitor.py:3782` |
| `SKIP_MARKET_DATA_STALE` | Market data > 30 minutes old | Stale data | `signal_monitor.py:1200` |
| `SKIP_NO_PRICE` | Current price is None or 0 | No price data | `signal_monitor.py:1200` |

### 4.3 Order Placement Gates
| Gate Name | Check | Block Reason | Location |
|-----------|-------|--------------|----------|
| `DRY_RUN` | `DRY_RUN=True` OR `live_trading=False` | Dry run mode | `crypto_com_trade.py:place_market_order()` |
| `INSUFFICIENT_BALANCE` | Available balance < order amount | Insufficient funds | `crypto_com_trade.py:place_market_order()` |
| `AUTH_FAILURE` | Exchange API authentication failed | Auth error | `crypto_com_trade.py:place_market_order()` |

---

## 5. Event Emission Points

### 5.1 Throttle Events
All events are recorded to `SignalThrottleState` via `record_signal_event()`:

| Event Type | When | What It Means | What It Does NOT Mean | Fields Recorded |
|------------|------|---------------|----------------------|-----------------|
| `ORDER_CREATED` | Order placed successfully | Order was submitted to exchange and accepted | Order is not yet executed | `symbol`, `side`, `order_id`, `price`, `quantity`, `timestamp` |
| `ORDER_EXECUTED` | Order filled (confirmed via order_history or trade_history) | Order was filled/executed - trade is complete | Does not mean order was canceled | `symbol`, `order_id`, `filled_qty`, `price`, `timestamp`, `status_source` |
| `ORDER_CANCELED` | Order canceled (confirmed via order_history or explicit cancel) | Order was canceled - trade did NOT execute | Does not mean order was executed | `symbol`, `order_id`, `reason`, `timestamp`, `status_source` |
| `ORDER_FAILED` | Order placement failed | Order could not be placed (error during creation) | Does not mean order was canceled or executed | `symbol`, `side`, `error`, `timestamp` |
| `SLTP_CREATED` | SL/TP orders created | Stop loss and take profit orders were placed | Does not mean primary order was executed | `symbol`, `sl_order_id`, `tp_order_id`, `timestamp` |
| `SLTP_FAILED` | SL/TP creation failed | SL/TP orders could not be created | Does not mean primary order failed | `symbol`, `error`, `timestamp` |
| `TRADE_BLOCKED` | Trade gate blocks order | Trade was prevented by a gate (cooldown, max orders, etc.) | Does not mean an order was placed | `symbol`, `side`, `gate_name`, `reason`, `timestamp` |
| `ALERT_EMITTED` | Alert sent to Telegram | Signal alert was sent to Telegram | Does not mean a trade happened | `symbol`, `side`, `price`, `strategy_key`, `timestamp` |

### 5.2 Telegram Events
All events are sent via `telegram_notifier`:

| Event Type | Function | When |
|------------|----------|------|
| `BUY_ALERT` | `send_buy_alert()` | BUY signal detected, alerts enabled, throttle allows |
| `SELL_ALERT` | `send_sell_alert()` | SELL signal detected, alerts enabled, throttle allows |
| `ORDER_CREATED` | `send_order_created()` | Primary order placed |
| `ORDER_FAILED` | `send_message()` | Order placement failed |
| `SLTP_CREATED` | `send_message()` | SL/TP orders created |
| `SLTP_FAILED` | `send_message()` (CRITICAL) | SL/TP creation failed |
| `ORDER_EXECUTED` | `send_executed_order()` | Order filled |
| `ORDER_CANCELED` | `send_message()` | Order cancelled |

---

## 6. Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. CONTINUOUS MONITORING (Every 30s)                           │
│    SignalMonitorService._monitor_signals()                     │
│    → Fetch market data → Calculate signals                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. SIGNAL DETECTION                                            │
│    buy_signal=True OR sell_signal=True                         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. ALERTS (if alert_enabled)                                   │
│    → Check throttle (price change + cooldown)                  │
│    → If allowed: Send Telegram + Record to throttle            │
│    → If blocked: Record TRADE_BLOCKED to throttle              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. TRADE GATE (if trade_enabled)                               │
│    → Check: trade_enabled, trade_amount_usd, max orders, etc. │
│    → If blocked: Record TRADE_BLOCKED + STOP                    │
│    → If allowed: Proceed to order placement                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. PRIMARY ORDER PLACEMENT                                     │
│    → place_market_order() → Exchange API                       │
│    → On success: Save to DB + Emit ORDER_CREATED               │
│    → On failure: Emit ORDER_FAILED + STOP                      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. POST-ORDER RISK ORDERS (SL/TP)                             │
│    → Poll for fill confirmation                                 │
│    → Create SL + TP orders                                     │
│    → On success: Emit SLTP_CREATED                             │
│    → On failure: Emit SLTP_FAILED                              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. EXECUTION/CANCEL EVENTS (Every 5s)                         │
│    ExchangeSyncService.sync_orders()                           │
│    → Detect status changes → Emit ORDER_EXECUTED/CANCELED      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 8. UI TABS                                                      │
│    → Open Orders: /api/open-orders (NEW/ACTIVE/PARTIALLY_FILLED)│
│    → Executed Orders: /api/executed-orders (FILLED/CANCELLED) │
│    → Monitoring: /api/monitoring/summary (active alerts)       │
│    → Throttle: /api/monitoring/telegram-messages (all events)  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Key Files Reference

| File | Purpose | Key Functions |
|------|---------|---------------|
| `signal_monitor.py` | Main lifecycle orchestrator | `_monitor_signals()`, `_create_buy_order()`, `_create_sell_order()` |
| `exchange_sync.py` | Order sync and SL/TP creation | `sync_orders()`, `_create_sl_tp_for_filled_order()` |
| `signal_throttle.py` | Throttling logic | `should_emit_signal()`, `record_signal_event()` |
| `trading_signals.py` | Signal calculation | `calculate_trading_signals()` |
| `strategy_profiles.py` | Strategy resolution | `resolve_strategy_profile()` |
| `crypto_com_trade.py` | Exchange API client | `place_market_order()`, `place_stop_loss_order()`, `place_take_profit_order()` |
| `telegram_notifier.py` | Telegram notifications | `send_buy_alert()`, `send_sell_alert()`, `send_order_created()`, etc. |
| `routes_monitoring.py` | Monitoring/throttle endpoints | `get_monitoring_summary()`, `get_telegram_messages()` |
| `routes_orders.py` | Orders endpoints | `get_open_orders()`, `get_executed_orders()` |

---

## 8. Configuration Files

| File | Purpose |
|------|---------|
| `trading_config.json` | Strategy presets per coin, defaults |
| `.env` / `.env.aws` | Environment variables (DRY_RUN, Telegram tokens, etc.) |
| `watchlist_items` table | Per-coin configuration (alerts, trading, strategy) |

---

**END OF SYSTEM MAP**



