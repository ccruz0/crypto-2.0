# Signal Flow Overview

**Last Updated:** 2025-12-01  
**Status:** ✅ Current Architecture Documentation

This document maps the data flow from exchange → signals → alerts → orders in the automated trading platform.

---

## 1. Data Sources

### 1.1 Market Data Collection

**Services:**
- `ExchangeSyncService` (`backend/app/services/exchange_sync.py`): Syncs exchange data every 5 seconds
- `MarketData` model (`backend/app/models/market_price.py`): Stores price, RSI, MAs, volume
- `MarketPrice` model: Stores current price per symbol

**Data Flow:**
```
Exchange API (Crypto.com)
  ↓
ExchangeSyncService (every 5s)
  ↓
MarketData table (price, RSI, ma50, ma200, ema10, volume, avg_volume)
  ↓
SignalMonitorService / routes_market.py
```

### 1.2 Price Fetching

**Services:**
- `price_fetcher` (`simple_price_fetcher.py`): Multi-source price fetcher (Crypto.com, Binance, etc.)
- `routes_market.py`: Dashboard endpoint that fetches prices for watchlist items

**Priority:**
1. `MarketData` table (cached, updated by `ExchangeSyncService`)
2. `MarketPrice` table (fallback)
3. Direct API call via `price_fetcher`

---

## 2. Signal Calculation

### 2.1 Entry Points

**Primary:**
- `SignalMonitorService._check_signal_for_coin_sync()`: Main monitoring loop (every 30s)
- `routes_market.py` `/dashboard` endpoint: Watchlist display (on-demand)

**Both call:**
- `calculate_trading_signals()` (`backend/app/services/trading_signals.py`)

### 2.2 calculate_trading_signals Flow

```
Input:
  - symbol, price, rsi, ma50, ma200, ema10, volume, avg_volume
  - buy_target, last_buy_price (from watchlist_item)
  - strategy_type, risk_approach (from resolve_strategy_profile)

Process:
  1. Load strategy rules from trading_config.json
  2. Evaluate BUY conditions (should_trigger_buy_signal):
     - RSI check (buy_rsi_ok)
     - MA check (buy_ma_ok) - respects strategy MA requirements
     - Volume check (buy_volume_ok)
     - Target check (buy_target_ok)
     - Price check (buy_price_ok)
  3. Calculate index: percentage of boolean buy_* flags that are True
  4. Apply canonical BUY rule: if all flags True → decision=BUY, buy_signal=True
  5. Evaluate SELL conditions (if decision != BUY):
     - RSI check (sell_rsi_ok)
     - Trend reversal (sell_trend_ok)
     - Volume check (sell_volume_ok)
  6. Set final decision (BUY takes priority over SELL)

Output:
  {
    "buy_signal": bool,
    "sell_signal": bool,
    "strategy": {
      "decision": "BUY" | "SELL" | "WAIT",
      "index": int (0-100),
      "reasons": { buy_rsi_ok, buy_ma_ok, ... }
    }
  }
```

### 2.3 Strategy Profile Resolution

**Function:** `resolve_strategy_profile()` (`backend/app/services/strategy_profiles.py`)

**Priority:**
1. Symbol-specific preset in `trading_config.json` → `coins.{symbol}.preset`
2. Default preset → `defaults.preset`
3. Fallback: `swing-conservative`

**Output:** `(StrategyType, RiskApproach)` tuple

---

## 3. Signal Monitoring

### 3.1 SignalMonitorService Flow

**Main Loop:** `SignalMonitorService.run_cycle()` (every 30 seconds)

```
For each watchlist item with alert_enabled=True:
  1. Fetch market data (price, RSI, MAs, volume) from MarketData table
  2. Call calculate_trading_signals() → get decision, buy_signal, sell_signal
  3. Check throttle (time + price change)
  4. If BUY/SELL and throttle allows:
     a. Send alert to Telegram (if alert_enabled + per-side toggle)
     b. Record in Monitoring (SENT status)
  5. If decision is WAIT:
     a. Record INFO monitoring entry (explaining why)
  6. If trade_enabled=True and amount_usd > 0:
     a. Check portfolio risk (portfolio_value <= 3x trade_amount)
     b. If risk OK → place order
     c. If risk blocks → record ORDER_BLOCKED_RISK (Monitoring only)
```

### 3.2 Alert Sending Path

**Function:** `SignalMonitorService._check_signal_for_coin_sync()`

**BUY Alert Flow:**
```python
if backend_decision == "BUY" and buy_signal:
    # 1. Check throttle
    buy_allowed, buy_reason = should_emit_signal(...)
    
    # 2. Check alert toggles
    if buy_allowed and alert_enabled and buy_alert_enabled:
        # 3. Send alert (Telegram + Monitoring)
        telegram_notifier.send_buy_signal(...)
        record_signal_event(...)  # Monitoring entry with SENT status
        
        # 4. Portfolio risk check (ONLY for order placement, not alerts)
        if trade_enabled and amount_usd > 0:
            ok_risk, risk_msg = check_portfolio_risk_for_order(...)
            if not ok_risk:
                record_order_risk_block(...)  # ORDER_BLOCKED_RISK
                return  # Skip order, but alert was already sent
            # Risk OK → place order
            place_buy_order(...)
```

**SELL Alert Flow:** (analogous)

### 3.3 Throttling

**Function:** `should_emit_signal()` (`backend/app/services/signal_throttle.py`)

**Rules:**
- **First alert** (WAIT → BUY/SELL): Always allowed
- **Repeated alerts** (BUY → BUY): Blocked if:
  - Time since last < `min_interval_minutes` **AND**
  - Price change < `min_price_change_pct`
- **Opposite side** (BUY → SELL): Always allowed

**State Storage:**
- `signal_throttle_states` table: `(symbol, strategy_key, side, timestamp, price)`

---

## 4. Order Placement

### 4.1 Order Creation Flow

**Function:** `SignalMonitorService._check_signal_for_coin_sync()` (order section)

**Conditions:**
1. `trade_enabled = True`
2. `amount_usd > 0`
3. `backend_decision == "BUY"` or `"SELL"`
4. Portfolio risk check passes

**Risk Check:**
```python
def check_portfolio_risk_for_order(symbol, side, trade_amount_usd, ...):
    portfolio_value = calculate_portfolio_value_for_symbol(...)
    limit_value = 3 * trade_amount_usd
    if portfolio_value > limit_value:
        return False, "Valor en cartera: ${portfolio_value} > límite: ${limit_value}"
    return True, "Risk OK"
```

**Order Creation:**
- Calls `trade_client.create_order()` (Crypto.com API)
- Creates `ExchangeOrder` record in database
- Sends order confirmation to Telegram

### 4.2 Risk Block Diagnostics

**Function:** `record_order_risk_block()` (`backend/app/api/routes_monitoring.py`)

**Behavior:**
- Inserts `telegram_messages` row with:
  - `throttle_status = "ORDER_BLOCKED_RISK"`
  - `delivery_channel = "MONITOR"`
  - `delivery_status = "INFO"`
- **NOT sent to Telegram** (Monitoring only)
- Message: "ORDEN BLOQUEADA POR VALOR EN CARTERA: ..."

---

## 5. BTC Index Monitor

### 5.1 BuyIndexMonitorService Flow

**Service:** `BuyIndexMonitorService` (`backend/app/services/buy_index_monitor.py`)

**Flow:**
```
Every 2 minutes:
  1. Check ENABLE_BTC_INDEX_ALERTS env var
  2. If false → log [BUY_INDEX_DISABLED] and return (no alert)
  3. If true:
     a. Fetch BTC_USD market data
     b. Call calculate_trading_signals() for BTC_USD
     c. Calculate buy index (0-100)
     d. Check throttle (time + price change)
     e. If throttle allows → send "BTC_USD BUY INDEX" alert to Telegram
```

**Throttling:**
- Uses same `should_emit_signal()` logic as regular alerts
- Minimum 10 minutes between alerts
- Minimum 1% price change

---

## 6. Frontend Display

### 6.1 Dashboard Endpoint

**Route:** `GET /api/dashboard` (`backend/app/api/routes_market.py`)

**Flow:**
```
For each watchlist item:
  1. Fetch market data (price, RSI, MAs, volume)
  2. Call calculate_trading_signals()
  3. Return coin object with:
     - strategy_state: { decision, index, reasons }
     - signal: "BUY" | "SELL" | "WAIT"
     - All market data (price, RSI, MAs, volume_ratio)
```

### 6.2 Frontend Rendering

**File:** `frontend/src/app/page.tsx`

**Signals Chip:**
```typescript
const decision = coin.strategy?.decision;  // Backend source of truth
let label: "BUY" | "SELL" | "WAIT" = "WAIT";
if (decision === "BUY") label = "BUY";
else if (decision === "SELL") label = "SELL";
// Render chip with label
```

**Index Label:**
```typescript
const index = coin.strategy?.index;  // Backend source of truth
// Render: INDEX: {index?.toFixed(1) ?? 0}%
```

**Tooltip:**
- Uses `coin.strategyReasons` (backend reasons) for ✓/✗ status
- Shows numeric values (RSI, volume ratio, MAs) as context
- No local rule computation

---

## 7. Monitoring Tab

### 7.1 Monitoring Endpoint

**Route:** `GET /api/monitoring/telegram-messages` (`backend/app/api/routes_monitoring.py`)

**Returns:**
- `SENT` alerts (Telegram messages that were sent)
- `BLOCKED` alerts (throttled)
- `INFO` diagnostics (WAIT decisions, order blocks)
- `ORDER_BLOCKED_RISK` entries (order risk blocks)

### 7.2 Monitoring Entry Types

**SENT:**
- `throttle_status = "SENT"`
- `delivery_channel = "TELEGRAM"`
- Sent to Telegram + shown in Monitoring

**BLOCKED (Throttle):**
- `throttle_status = "BLOCKED"`
- `throttle_reason = "time" | "price"`
- Shown in Monitoring only

**INFO (Diagnostics):**
- `delivery_status = "INFO"`
- `delivery_channel = "MONITOR"`
- Explains why no alert was sent (WAIT decision, flags false, etc.)

**ORDER_BLOCKED_RISK:**
- `throttle_status = "ORDER_BLOCKED_RISK"`
- `delivery_channel = "MONITOR"`
- `delivery_status = "INFO"`
- Explains why order was blocked (portfolio value too high)

---

## 8. Key Principles

### 8.1 Separation of Concerns

1. **Signal Calculation**: Pure function, independent of position/orders
2. **Alert Sending**: Depends only on decision, signal flags, toggles, throttle
3. **Order Placement**: Depends on decision, signal flags, trade toggles, risk

### 8.2 Source of Truth

- **Backend decision**: `strategy_state["decision"]` from `calculate_trading_signals()`
- **Backend index**: `strategy_state["index"]` from same flags as decision
- **Backend reasons**: `strategy_state["reasons"]` (buy_rsi_ok, buy_ma_ok, etc.)
- **Frontend**: Must trust backend data, no local recomputation

### 8.3 Portfolio Risk

- **Never blocks alerts**: Alerts are sent based on strategy decision only
- **Only blocks orders**: Risk check happens in order placement section
- **Diagnostics**: ORDER_BLOCKED_RISK entries explain why order was blocked

---

## 9. Data Flow Diagram

```
┌─────────────────┐
│ Exchange API    │
│ (Crypto.com)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ExchangeSync    │ (every 5s)
│ Service         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ MarketData      │ (price, RSI, MAs, volume)
│ Table           │
└────────┬────────┘
         │
         ├─────────────────┐
         │                  │
         ▼                  ▼
┌─────────────────┐  ┌─────────────────┐
│ SignalMonitor   │  │ routes_market   │
│ Service         │  │ /dashboard      │
│ (every 30s)     │  │ (on-demand)     │
└────────┬────────┘  └────────┬────────┘
         │                    │
         └──────────┬──────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │ calculate_trading    │
         │ _signals()           │
         └──────────┬───────────┘
                    │
         ┌──────────┴───────────┐
         │                      │
         ▼                      ▼
┌─────────────────┐    ┌─────────────────┐
│ Alert Path      │    │ Order Path      │
│ (always runs)   │    │ (if trade=YES)  │
│                 │    │                 │
│ 1. Check throttle│    │ 1. Check risk  │
│ 2. Send alert   │    │ 2. Place order  │
│ 3. Record SENT  │    │ 3. Record order  │
└─────────────────┘    └─────────────────┘
```

---

## 10. Error Handling

### 10.1 Missing Data

- **RSI missing**: `buy_rsi_ok = False` (blocks BUY)
- **MAs missing**: If required → `buy_ma_ok = False`; if not required → `buy_ma_ok = True`
- **Volume missing**: `buy_volume_ok = True` (assumed OK)

### 10.2 Service Failures

- **Exchange API down**: Use cached `MarketData` from database
- **Database error**: Log error, skip symbol, continue with next
- **Telegram error**: Log error, continue (don't block signal evaluation)

---

## 11. Performance Considerations

### 11.1 Caching

- `MarketData` table: Updated every 5s by `ExchangeSyncService`
- `routes_market.py`: Uses cached data, avoids API calls when possible
- `SignalMonitorService`: Reads from `MarketData` table (fast)

### 11.2 Throttling

- Prevents alert spam (same decision, small price changes)
- State stored in `signal_throttle_states` table
- Queries are indexed by `(symbol, strategy_key, side)`

---

## 12. Testing Points

### 12.1 Unit Tests

- `calculate_trading_signals()`: Test canonical BUY rule, index calculation
- `should_trigger_buy_signal()`: Test RSI, MA, volume checks
- `should_emit_signal()`: Test throttle logic

### 12.2 Integration Tests

- `SignalMonitorService`: Test alert sending, order placement, risk blocks
- `routes_market.py`: Test dashboard endpoint returns correct strategy data
- Frontend: Test Signals chip displays backend decision correctly

---

## 13. Change History

- **2025-12-01**: Initial signal flow documentation created
- Based on code analysis of `signal_monitor.py`, `trading_signals.py`, `routes_market.py`





