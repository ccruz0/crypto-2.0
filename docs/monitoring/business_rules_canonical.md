# Canonical Business Rules for Trading Platform

**Last Updated:** 2025-12-01  
**Status:** ✅ Authoritative Source of Truth

This document defines the canonical business rules for the automated trading platform. All code must align with these rules.

---

## 1. Signal Rules

### 1.1 BUY Conditions

BUY conditions are defined by **presets** in `backend/trading_config.json`. Each preset has:
- **Strategy type**: `swing`, `intraday`, or `scalp`
- **Risk approach**: `Conservative` or `Aggressive`
- **Rules**: RSI thresholds, volume ratios, MA requirements, etc.

#### Preset Structure

```json
{
  "presets": {
    "scalp": {
      "rules": {
        "Aggressive": {
          "rsi": { "buyBelow": 55, "sellAbove": 65 },
          "maChecks": { "ema10": true, "ma50": false, "ma200": false },
          "volumeMinRatio": 0.5,
          "minPriceChangePct": 1.0,
          "alertCooldownMinutes": 5.0
        }
      }
    }
  }
}
```

#### BUY Condition Evaluation

For each preset, BUY requires **ALL** of the following conditions to be `True`:

1. **RSI Check** (`buy_rsi_ok`):
   - `RSI < rsi.buyBelow` (from preset config)
   - If RSI is `None` → `buy_rsi_ok = False`
   - If `rsi.buyBelow` is `None` → `buy_rsi_ok = True` (no RSI threshold configured)

2. **MA Check** (`buy_ma_ok`):
   - **If strategy requires MAs** (`maChecks.ema10=true` or `maChecks.ma50=true` or `maChecks.ma200=true`):
     - When both `ma50` and `ema10` are checked: `MA50 > EMA10` (with 0.5% tolerance for flat markets)
     - When only `ma50` is checked: `Price > MA50` (with 0.5% tolerance)
     - When `ma200` is checked: `Price > MA200` (with 0.5% tolerance)
     - **Tolerance**: Price can be up to **0.5% below MA** and still count as "above MA"
     - **Flat market**: If `abs(MA50 - EMA10) < 0.0001`, treat as flat and allow BUY
   - **If strategy does NOT require MAs** (all `maChecks.* = false`):
     - `buy_ma_ok = True` (not blocking)
   - If MAs are required but missing → `buy_ma_ok = False`

3. **Volume Check** (`buy_volume_ok`):
   - `volume_ratio >= volumeMinRatio` (from preset config, default 0.5)
   - `volume_ratio = current_volume / avg_volume`
   - **If volume data is missing** → `buy_volume_ok = True` (assumed OK, matches frontend behavior)

4. **Buy Target Check** (`buy_target_ok`):
   - If `buy_target` is set: `price <= buy_target`
   - If `buy_target` is `None` → `buy_target_ok = True` (not blocking)

5. **Price Check** (`buy_price_ok`):
   - `price > 0` and `price` is valid
   - Always `True` for valid price data

#### Strategy-Specific Examples

**scalp-aggressive** (used by ALGO_USDT, LDO_USDT, TON_USDT):
- RSI: `buyBelow = 55`
- MAs: **NOT required** (all `maChecks.* = false` in current settings)
  - If `ema10=false`, `ma50=false`, `ma200=false` → `buy_ma_ok = True` (not blocking)
- Volume: `minRatio = 0.5`
- **BUY requires**: RSI < 55 AND volume_ratio >= 0.5 AND price <= buy_target (if set)
- **Note**: EMA10 check only applies if `maChecks.ema10=true` in config. If not marked as required in Signal Config UI, it is NOT checked.

**swing-conservative**:
- RSI: `buyBelow = 40`
- MAs: **Required** (`ema10=true`, `ma50=true`, `ma200=true`)
- Volume: `minRatio = 0.5`
- **BUY requires**: RSI < 40 AND MA50 > EMA10 AND Price > MA200 AND volume_ratio >= 0.5

### 1.2 SELL Conditions

SELL requires **ALL** of the following:

1. **RSI Check** (`sell_rsi_ok`):
   - `RSI > rsi.sellAbove` (from preset config, typically 65-70)

2. **Trend Reversal** (`sell_trend_ok`):
   - **If strategy requires MA checks**: `MA50 < EMA10` (with >= 0.5% difference) OR `Price < MA10w`
   - **If strategy does NOT require MAs**: `sell_trend_ok = True` (not blocking)

3. **Volume Check** (`sell_volume_ok`):
   - `volume_ratio >= volumeMinRatio` (same as BUY)
   - If volume data missing → `sell_volume_ok = True`

**Important**: SELL must **NEVER override BUY** in the same cycle. If canonical BUY rule sets `decision=BUY`, SELL logic is skipped.

---

## 2. Decision & Flags

### 2.1 calculate_trading_signals Output

The `calculate_trading_signals()` function must produce:

```python
{
    "buy_signal": bool,      # True if all buy_* flags are True
    "sell_signal": bool,     # True if all sell_* flags are True
    "strategy": {
        "decision": "BUY" | "SELL" | "WAIT",
        "index": int | None,  # 0-100, percentage of buy_* flags that are True
        "reasons": {
            "buy_rsi_ok": bool | None,
            "buy_ma_ok": bool | None,
            "buy_volume_ok": bool | None,
            "buy_target_ok": bool | None,
            "buy_price_ok": bool | None,
            "sell_rsi_ok": bool | None,
            "sell_trend_ok": bool | None,
            "sell_volume_ok": bool | None,
        }
    }
}
```

### 2.2 Canonical BUY Rule

**PRIMARY RULE**: If **ALL** boolean `buy_*` flags are `True`, then:
- `strategy_state["decision"] = "BUY"`
- `result["buy_signal"] = True`

**Implementation**:
```python
buy_flags = [
    buy_rsi_ok,
    buy_ma_ok,
    buy_volume_ok,
    buy_target_ok,
    buy_price_ok,
]
effective_buy_flags = [f for f in buy_flags if isinstance(f, bool)]
if effective_buy_flags and all(effective_buy_flags):
    strategy_state["decision"] = "BUY"
    result["buy_signal"] = True
```

**Note**: `None` values are excluded (mean "not applicable" or "not blocking").

### 2.3 Index Calculation

`strategy_state["index"]` is calculated as:
- **Percentage of boolean `buy_*` flags that are `True`**
- Formula: `(satisfied_count / total_count) * 100`
- **100% index** = ALL required BUY flags are `True` (matches canonical BUY rule)
- **0% index** = ALL required BUY flags are `False`
- **Partial** = Some flags True, some False (e.g., 3/5 = 60%)

**Critical**: Index must be derived from the **same flags** used by the canonical BUY rule. There must be no hidden conditions that affect decision but not index (or vice versa).

### 2.4 SELL Logic

SELL logic must:
1. Check if `strategy_state["decision"] != "BUY"` before setting SELL
2. Compute `sell_*` flags in the same structured way
3. Set `decision="SELL"` only if BUY was not triggered

```python
if any(sell_conditions) and strategy_state["decision"] != "BUY":
    result["sell_signal"] = True
    strategy_state["decision"] = "SELL"
```

---

## 3. Alerts vs Orders

### 3.1 Alert Sending Rules

**Alerts** (Telegram messages + Monitoring entries) depend **ONLY** on:

1. **Strategy decision**: `strategy_state["decision"]` ∈ {"BUY", "SELL", "WAIT"}
2. **Signal flags**: `buy_signal` or `sell_signal` from `calculate_trading_signals`
3. **Alert toggles**:
   - `watchlist_item.alert_enabled` (master switch)
   - `watchlist_item.buy_alert_enabled` (BUY-specific)
   - `watchlist_item.sell_alert_enabled` (SELL-specific)
4. **Throttling logic**:
   - Minimum time between alerts (e.g., 10 minutes)
   - Minimum price change percentage (e.g., 1%)

**Portfolio risk limits NEVER block alerts.**

### 3.2 Order Placement Rules

**Orders** (actual trades on exchange) depend on:

1. **All alert conditions** (decision, signal, toggles, throttle)
2. **Trade toggles**:
   - `watchlist_item.trade_enabled` (must be `True`)
   - `watchlist_item.trade_amount_usd` (must be `> 0`)
3. **Portfolio risk check**:
   - `portfolio_value_usd <= 3 * trade_amount_usd`
   - If risk check fails → order is **blocked**, but alert was already sent

### 3.3 Risk Block Messages

When portfolio risk blocks an order:
- **Message text**: "ORDEN BLOQUEADA POR VALOR EN CARTERA" (not "ALERTA BLOQUEADA")
- **Status**: `ORDER_BLOCKED_RISK` (not `BLOCKED`)
- **Channel**: Monitoring only (not sent to Telegram)
- **Timing**: Logged **after** alert is sent, **before** order placement

**Old text "ALERTA BLOQUEADA POR VALOR EN CARTERA" must not appear anywhere.**

---

## 4. Throttling

### 4.1 Throttle Rules

Per symbol/strategy throttle with:

1. **Minimum time between alerts** (`min_interval_minutes`):
   - Default: 5-10 minutes (configurable per preset)
   - Applies to repeated alerts with the **same decision**
   - **Does NOT prevent** the initial alert when conditions flip from WAIT → BUY/SELL

2. **Minimum price change** (`min_price_change_pct`):
   - Default: 1.0% (configurable per preset)
   - Applies to repeated alerts with the **same decision**
   - **Does NOT prevent** the initial alert when conditions flip from WAIT → BUY/SELL

### 4.2 Throttle Behavior

- **First alert** (WAIT → BUY/SELL): Always allowed (no throttle check)
- **Repeated alerts** (BUY → BUY, SELL → SELL): Blocked if:
  - Time since last alert < `min_interval_minutes` **AND**
  - Price change < `min_price_change_pct`
- **Opposite side alerts** (BUY → SELL, SELL → BUY): Always allowed (no throttle)

**Note:** Throttle rules apply **equally** to both BUY and SELL alerts. SELL alerts use the same cooldown and price-change thresholds as BUY alerts.

### 4.3 LOCAL vs AWS Alert Origins

- **AWS Runtime** (`RUNTIME_ORIGIN=AWS`):
  - Sends production alerts to Telegram
  - All alerts prefixed with `[AWS]`
  - Throttle state persisted in database (`SignalThrottleState` table)
  - Respects all throttle rules (cooldown + price change)

- **LOCAL Runtime** (`RUNTIME_ORIGIN=LOCAL`):
  - Alerts are **blocked** from reaching Telegram
  - Logs `[TG_LOCAL_DEBUG]` instead of sending
  - Still respects throttle rules in logs (for debugging consistency)
  - Dashboard shows `[LOCAL DEBUG]` prefix for blocked alerts

**Important:** LOCAL alerts cannot bypass throttle rules. Even though they don't reach Telegram, throttle decisions are still logged with `origin=LOCAL` for debugging.

### 4.4 Telegram Alert Origin Gatekeeper

**CRITICAL RULE:** Only the AWS runtime (origin = "AWS") is allowed to send alerts to the production Telegram chat.

**Implementation:**
- All alert-sending functions (`send_message`, `send_buy_signal`, `send_sell_signal`) accept an `origin` parameter
- The central gatekeeper in `send_message()` blocks all non-AWS origins:
  - If `origin != "AWS"`: Message is logged with `[TG_LOCAL_DEBUG]` but NOT sent to Telegram
  - If `origin == "AWS"`: Message is sent to Telegram with `[AWS]` prefix
- Local/debug runs (origin = "LOCAL" or "DEBUG") can still compute signals and log what WOULD have been sent, but they never send messages to Telegram

**Call Sites:**
- `SignalMonitorService` (production): Always passes `origin=get_runtime_origin()` (which is "AWS" in production)
- Test endpoints (`/api/test/simulate-alert`): Always passes `origin="LOCAL"` to prevent test alerts from reaching production Telegram
- Any debug scripts: Should explicitly pass `origin="LOCAL"` or `origin="DEBUG"`

**Logging:**
- Blocked alerts are logged: `[TG_LOCAL_DEBUG] Skipping Telegram send for non-AWS origin 'LOCAL'. Message would have been: ...`
- Sent alerts are logged: `Telegram message sent successfully (origin=AWS)`

---

## 5. BTC Index Switch

### 5.1 Configuration

- **Environment variable**: `ENABLE_BTC_INDEX_ALERTS`
- **Type**: Boolean (string: "true" or "false")
- **Default**: `false` (alerts disabled by default in production)

### 5.2 Behavior

**When `ENABLE_BTC_INDEX_ALERTS=false`**:
- `BuyIndexMonitorService` still calculates BTC index internally
- **No Telegram messages** are sent for "BTC_USD BUY INDEX" alerts
- Logs show: `[BUY_INDEX_DISABLED] BTC index alerts are disabled by config`
- Monitor continues to track index values but does not emit alerts

**When `ENABLE_BTC_INDEX_ALERTS=true`**:
- Normal BTC index alerts are sent to Telegram
- Alerts respect existing throttling rules

---

## 6. Monitoring Rules

### 6.1 Alert States

Every time a symbol with `ALERTS=ON` is evaluated:

1. **If BUY/SELL alert is sent**:
   - Appears as `SENT` in Monitoring tab
   - Sent to Telegram (if enabled)
   - Status: `SENT`

2. **If no alert is sent because decision is WAIT**:
   - An `INFO` monitoring entry explains why:
     - Which `buy_*` flags are `False`
     - Whether throttle blocked it
   - Status: `INFO`
   - Channel: `MONITOR` (not sent to Telegram)

3. **If order is blocked by risk**:
   - An `ORDER_BLOCKED_RISK` entry appears in Monitoring
   - Status: `ORDER_BLOCKED_RISK`
   - Channel: `MONITOR` (not sent to Telegram)
   - Message: "ORDEN BLOQUEADA POR VALOR EN CARTERA: ..."

### 6.2 State Caching

To prevent spamming Monitoring with identical diagnostics:
- Track last monitor state per `(symbol, side, strategy_key)`
- Only record new `INFO` entry when state changes:
  - WAIT → BUY/SELL
  - BUY/SELL → WAIT
  - Throttle blocked → Allowed
  - etc.

---

## 7. Symbol Configuration

### 7.1 Preset Assignment

Symbols are assigned presets in `backend/trading_config.json`:

```json
{
  "coins": {
    "ALGO_USDT": { "preset": "scalp-aggressive" },
    "LDO_USDT": { "preset": "scalp-aggressive" },
    "TON_USDT": { "preset": "scalp-aggressive" }
  }
}
```

### 7.2 Preset Resolution

Priority order:
1. Symbol-specific preset in `trading_config.json` → `coins.{symbol}.preset`
2. Default preset from `trading_config.json` → `defaults.preset`
3. Fallback: `swing-conservative`

---

## 8. Data Flow Principles

### 8.1 Signal Calculation

- **Input**: Market data (price, RSI, MAs, volume) + strategy config
- **Output**: Decision, flags, index, signals
- **Independent of**: Position state (`last_buy_price`), order state, portfolio value
- **Position checks belong ONLY in order placement layer**, not signal calculation

### 8.2 Alert Sending

- **Input**: Decision + signal flags + alert toggles + throttle state
- **Output**: Telegram message + Monitoring entry
- **Independent of**: Portfolio risk, order placement

### 8.3 Order Placement

- **Input**: Decision + signal flags + trade toggles + portfolio risk
- **Output**: Exchange order (or ORDER_BLOCKED_RISK diagnostic)
- **Dependent on**: Alert was already sent (or would be sent if enabled)

---

## 9. Frontend Display Rules

### 9.1 Signals Chip

- **Source of truth**: `coin.strategy?.decision` from backend
- **Display logic**:
  ```typescript
  const decision = coin.strategy?.decision;
  let label: "BUY" | "SELL" | "WAIT" = "WAIT";
  if (decision === "BUY") label = "BUY";
  else if (decision === "SELL") label = "SELL";
  // Use label for chip color and text
  ```
- **No local recomputation** of RSI/MA/volume conditions

### 9.2 Index Label

- **Source of truth**: `coin.strategy?.index` from backend
- **Display**: `INDEX: {index?.toFixed(1) ?? 0}%`
- **No client-side index calculation**

### 9.3 Tooltip

- **Source of truth**: `coin.strategyReasons` (backend reasons)
- **Display**: Use `buy_rsi_ok`, `buy_volume_ok`, etc. for ✓/✗ status
- **Show numeric values** (RSI, volume ratio, MAs) as read-only context
- **No local rule implementation** (e.g., don't check "RSI < 55" on frontend)

---

## 10. Logging Standards

### 10.1 Structured Logs

**Single structured log at end of `calculate_trading_signals`**:
```
DEBUG_STRATEGY_FINAL | symbol={symbol} | decision={decision} | buy={buy_signal} | sell={sell_signal} | 
buy_rsi_ok={buy_rsi_ok} | buy_ma_ok={buy_ma_ok} | buy_volume_ok={buy_volume_ok} | 
buy_target_ok={buy_target_ok} | buy_price_ok={buy_price_ok} | index={index}
```

**Before canonical rule**:
```
DEBUG_BUY_FLAGS | symbol={symbol} | rsi_ok={buy_rsi_ok} | ma_ok={buy_ma_ok} | 
vol_ok={buy_volume_ok} | target_ok={buy_target_ok} | price_ok={buy_price_ok} | index={index_preview}
```

**Profile resolution**:
```
DEBUG_RESOLVED_PROFILE | symbol={symbol} | preset={preset_name}
```

### 10.2 Remove Noisy Logs

- Remove duplicate or verbose debug logs that are no longer needed
- Keep only the structured logs above for production debugging

---

## 11. Testing Requirements

### 11.1 Unit Tests

Must test:
- Canonical BUY rule: all flags True → decision=BUY, index=100
- Partial flags: some True, some False → index reflects percentage
- SELL does not override BUY
- Portfolio risk blocks orders, not alerts

### 11.2 Integration Tests

Must verify:
- Alert sent when decision=BUY and alerts enabled
- Order blocked when risk too high, but alert still sent
- Monitoring shows INFO entries for WAIT decisions
- Frontend displays backend decision correctly

---

## 12. Deployment Checklist

Before deploying:
- [ ] All references to "ALERTA BLOQUEADA POR VALOR EN CARTERA" removed
- [ ] Only "ORDEN BLOQUEADA POR VALOR EN CARTERA" remains (for order diagnostics)
- [ ] Frontend uses `coin.strategy?.decision` and `coin.strategy?.index` directly
- [ ] Backend canonical rule implemented correctly
- [ ] SignalMonitor uses backend decision (not recomputing)
- [ ] Tests passing
- [ ] Lint passing

---

## 13. Change History

- **2025-12-01**: Initial canonical rules document created
- Based on existing docs: `portfolio_risk_refactor.md`, `buy_signal_logic_fix.md`, `btc_index_switch.md`

