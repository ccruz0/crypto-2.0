# Portfolio Value Risk Check Alignment

## Problem Summary

Risk check messages showed portfolio values (e.g., $3513.xx for CRO_USDT) that didn't match what users saw in the Portfolio tab, causing confusion.

## Root Cause

**Risk Check (Old)**:
- Used only FILLED orders from `exchange_orders` table
- Calculated: `(filled_buy_qty - filled_sell_qty) * current_price`
- Did NOT include: manual deposits, balances from external orders, or open orders

**Portfolio Tab**:
- Used actual exchange balances from Crypto.com API
- Stored in `portfolio_balances` table
- Shows ALL balances regardless of source

## Solution

### 1. Changed Portfolio Value Calculation

Modified `calculate_portfolio_value_for_symbol` in `backend/app/services/order_position_service.py` to:

1. **Use Exchange Balances** (same source as Portfolio tab):
   - Query `PortfolioBalance` table for the symbol's base currency
   - Extract base currency (e.g., "CRO" from "CRO_USDT")
   - Sum all balance entries for that currency
   - Use `usd_value` from the table (or calculate `balance_qty * current_price`)

2. **Optionally Include Open BUY Orders**:
   - Configurable via `INCLUDE_OPEN_ORDERS_IN_RISK = True`
   - Sums pending BUY orders (NEW/ACTIVE/PARTIALLY_FILLED)
   - Calculates: `order_qty * order_price` for each open order

3. **Final Calculation**:
   - `portfolio_value_usd = balance_value_usd + open_buy_value_usd` (if open orders enabled)
   - `portfolio_value_usd = balance_value_usd` (if open orders disabled)

### 2. Enhanced Error Messages

Updated risk check messages to include breakdown:

**Without open orders**:
```
🚫 ALERTA BLOQUEADA POR VALOR EN CARTERA: CRO_USDT - 
Valor en cartera: $3513.85 USD (balance actual en exchange). 
Límite: $300.00 (3x trade_amount)
```

**With open orders**:
```
🚫 ALERTA BLOQUEADA POR VALOR EN CARTERA: CRO_USDT - 
Valor en cartera: $3513.85 USD = $3000.00 balance + $513.85 órdenes abiertas. 
Límite: $300.00 (3x trade_amount)
```

### 3. Simplified Logging

Added concise logging for all symbols:
```
[RISK_PORTFOLIO_CHECK] symbol=CRO_USDT base_currency=CRO balance_qty=12345.67890000 
balance_value_usd=3513.85 open_buy_orders_count=2 open_buy_value_usd=513.85 
total_value_usd=4027.70 include_open_orders=True
```

## Files Changed

1. **backend/app/services/order_position_service.py**:
   - Rewrote `calculate_portfolio_value_for_symbol` to use `PortfolioBalance` table
   - Added `INCLUDE_OPEN_ORDERS_IN_RISK` configuration flag
   - Changed return value: `(portfolio_value_usd, balance_qty)` instead of `(portfolio_value_usd, net_quantity)`
   - Simplified logging to one concise line per call

2. **backend/app/services/signal_monitor.py**:
   - Updated all 3 portfolio value risk checks to use new calculation
   - Enhanced error messages with breakdown (balance + open orders)
   - Added detailed logging with breakdown values
   - Imported `_normalized_symbol_filter` and `INCLUDE_OPEN_ORDERS_IN_RISK`

## Configuration

- **`INCLUDE_OPEN_ORDERS_IN_RISK`**: Set to `True` to include pending BUY orders in portfolio value calculation
  - Location: `backend/app/services/order_position_service.py`
  - Default: `True`

## Benefits

1. **Alignment**: Risk check now uses the same data source as Portfolio tab
2. **Transparency**: Error messages clearly show where the value comes from
3. **Accuracy**: Includes all balances, not just tracked orders
4. **Flexibility**: Can include/exclude open orders via configuration

## Verification

After deployment, check logs for:
```
[RISK_PORTFOLIO_CHECK] symbol=CRO_USDT ...
```

This will show:
- `balance_qty`: Total balance quantity from exchange
- `balance_value_usd`: USD value of exchange balance
- `open_buy_orders_value_usd`: USD value of pending BUY orders (if enabled)
- `total_value_usd`: Final portfolio value used for risk check
- `blocked`: Whether the check blocked the alert/order

The value should now match what's shown in the Portfolio tab.





