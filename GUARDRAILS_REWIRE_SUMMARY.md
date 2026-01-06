# Guardrails Rewire Summary

## Files Changed

1. **backend/app/utils/trading_guardrails.py** - Completely rewired to use true sources of truth
2. **backend/app/api/routes_orders.py** - Updated to use `can_place_real_order` (was `check_trading_guardrails`)
3. **backend/app/services/signal_monitor.py** - Updated to use `can_place_real_order`
4. **backend/tests/test_trading_guardrails_rewire.py** - New tests for rewired guardrails
5. **backend/tests/test_trading_guardrails.py** - Updated to work with new guardrails (backward compatibility)

## Source of Truth Mapping

### 1. Live Toggle (Dashboard)
- **Storage**: `TradingSettings` table, `setting_key="LIVE_TRADING"`, `setting_value="true"|"false"`
- **Read Function**: `get_live_trading_status(db)` in `backend/app/utils/live_trading.py`
- **Update Endpoint**: `POST /api/trading/live-toggle` in `backend/app/api/routes_control.py`
- **Fallback**: Environment variable `LIVE_TRADING` if DB setting not found

### 2. Telegram Kill Switch (Global)
- **Storage**: `TradingSettings` table, `setting_key="TRADING_KILL_SWITCH"`, `setting_value="true"|"false"`
- **Read Function**: `_get_telegram_kill_switch_status(db)` in `backend/app/utils/trading_guardrails.py`
- **Default**: `false` (kill switch OFF, trading allowed) if not set
- **Note**: This is a NEW setting - infrastructure created but not yet used by Telegram commands

### 3. Trade Yes Per Symbol
- **Storage**: `WatchlistItem.trade_enabled` column (Boolean) in `watchlist_items` table
- **Read Function**: `_get_trade_enabled_for_symbol(db, symbol)` in `backend/app/utils/trading_guardrails.py`
- **Model**: `backend/app/models/watchlist.py`, line 25

## Check Order

The `can_place_real_order()` function checks in this order:

1. **Live toggle must be ON** (TradingSettings.LIVE_TRADING)
2. **Telegram kill switch must be OFF** (TradingSettings.TRADING_KILL_SWITCH)
3. **Trade Yes for symbol must be YES** (WatchlistItem.trade_enabled)
4. **TRADING_ENABLED env** (optional final override - if false, always block)
5. **Optional allowlist** (TRADE_ALLOWLIST, if set - defaults to no restriction when empty)
6. **Risk limits** (MAX_OPEN_ORDERS_TOTAL, MAX_ORDERS_PER_SYMBOL_PER_DAY, MAX_USD_PER_ORDER, MIN_SECONDS_BETWEEN_ORDERS)

## Changes Summary

- ✅ Removed TRADE_ALLOWLIST from primary path (now optional, defaults to no restriction)
- ✅ Added Live toggle check (must be ON)
- ✅ Added Telegram kill switch check (must be OFF)
- ✅ Added Trade Yes per symbol check (must be YES)
- ✅ TRADING_ENABLED env is now optional final override (if false, always block; if true, does NOT override Live OFF or Trade Yes OFF)
- ✅ All existing risk limits preserved
- ✅ Backward compatibility: `check_trading_guardrails` is now an alias for `can_place_real_order`

## Integration Points

- ✅ `routes_orders.py`: Manual orders (BUY/SELL)
- ✅ `signal_monitor.py`: Automatic orders (BUY)
- ⚠️ SL/TP creation paths: Not updated (protection orders for existing positions - may need different logic)

## Tests

- ✅ New tests in `test_trading_guardrails_rewire.py` (8 tests, all passing):
  - Live OFF blocks orders even if TRADING_ENABLED=true
  - Telegram kill switch ON blocks orders even if Live ON and TradeYes YES
  - Trade Yes OFF blocks orders even if Live ON
  - TRADING_ENABLED=false always blocks
  - TRADING_ENABLED=true does NOT override Live OFF
- ✅ Updated existing tests in `test_trading_guardrails.py` (10 tests, all passing) to work with new guardrails
- ✅ All 18 tests pass successfully

