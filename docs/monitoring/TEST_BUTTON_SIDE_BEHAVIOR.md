# TEST Button Side Behavior

## Overview

The TEST button in the Watchlist table now intelligently determines which side (BUY or SELL) to simulate based on the enabled alert toggles and the current signal state.

## Behavior Rules

### 1. Only BUY Enabled
- **Condition**: `buy_alert_enabled = true`, `sell_alert_enabled = false`
- **Action**: TEST simulates a **BUY** alert
- **Example**: User enables BUY toggle only → TEST button sends BUY test alert

### 2. Only SELL Enabled
- **Condition**: `buy_alert_enabled = false`, `sell_alert_enabled = true`
- **Action**: TEST simulates a **SELL** alert
- **Example**: User enables SELL toggle only → TEST button sends SELL test alert

### 3. Both BUY and SELL Enabled
- **Condition**: `buy_alert_enabled = true`, `sell_alert_enabled = true`
- **Action**: TEST uses the **current signal side** from the backend (`strategy_state.decision`)
  - If `decision = "BUY"` → TEST simulates BUY alert
  - If `decision = "SELL"` → TEST simulates SELL alert
  - If `decision = "WAIT"` or unavailable → TEST defaults to BUY (fallback)
- **Example**: Both toggles ON, current signal is SELL → TEST button sends SELL test alert

### 4. Neither Enabled
- **Condition**: `buy_alert_enabled = false`, `sell_alert_enabled = false`
- **Action**: TEST does **NOT** call any alert endpoint
- **User Message**: Shows alert: "⚠️ Alerts deshabilitados\n\nEl campo 'Alerts' está en OFF para este símbolo.\n\nPor favor activa BUY o SELL para poder ejecutar una prueba."
- **Example**: Both toggles OFF → TEST button shows error message, no alert sent

## Implementation Details

### Frontend (`frontend/src/app/page.tsx`)
- TEST button handler checks `coinBuyAlertStatus[symbol]` and `coinSellAlertStatus[symbol]`
- Reads current signal from `coin.strategy_state.decision`
- Calls `simulateAlert(symbol, testSide, ...)` with determined side
- Shows confirmation dialog with the determined side before executing

### Backend (`backend/app/api/routes_test.py`)
- Endpoint `/api/test/simulate-alert` accepts `signal_type: "BUY" | "SELL"`
- Both BUY and SELL paths call `telegram_notifier.send_*_signal(..., origin="LOCAL")`
- Test alerts are blocked by the origin gatekeeper (logged but not sent to production Telegram)

## Origin Gatekeeper Integration

All test alerts use `origin="LOCAL"`, which means:
- ✅ Test alerts are logged with `[TG_LOCAL_DEBUG]` prefix
- ✅ Test alerts are registered in Monitoring → Telegram Messages (marked as blocked)
- ❌ Test alerts are **NOT** sent to production Telegram chat
- ✅ This prevents accidental test alerts from reaching production

## Examples

### Example 1: BUY Only Enabled
```
Symbol: ALGO_USDT
BUY toggle: ✅ ON
SELL toggle: ❌ OFF
Current signal: WAIT
→ TEST button simulates BUY alert
```

### Example 2: SELL Only Enabled
```
Symbol: ALGO_USDT
BUY toggle: ❌ OFF
SELL toggle: ✅ ON
Current signal: WAIT
→ TEST button simulates SELL alert
```

### Example 3: Both Enabled, Current Signal is SELL
```
Symbol: ALGO_USDT
BUY toggle: ✅ ON
SELL toggle: ✅ ON
Current signal: SELL
→ TEST button simulates SELL alert (uses current signal side)
```

### Example 4: Both Disabled
```
Symbol: ALGO_USDT
BUY toggle: ❌ OFF
SELL toggle: ❌ OFF
→ TEST button shows error message, no alert sent
```

## Related Documentation

- `docs/monitoring/business_rules_canonical.md` - Business rules for alerts
- `docs/monitoring/TELEGRAM_ORIGIN_GATEKEEPER_SUMMARY.md` - Origin gatekeeper details






