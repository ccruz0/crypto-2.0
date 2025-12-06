# Portfolio Value Calculation for Risk Checks

## Problem Summary

Risk check messages show "ALERTA BLOQUEADA POR VALOR EN CARTERA" with a portfolio value (e.g., $3513.xx for CRO_USDT) that doesn't match what's visible in the Portfolio tab.

## Root Cause Analysis

### Risk Check Calculation (`calculate_portfolio_value_for_symbol`)

The risk check uses **only filled orders** from the `exchange_orders` table:

1. **Filled BUY orders**: Sums all FILLED BUY orders (excluding STOP_LOSS/TAKE_PROFIT roles)
2. **Filled SELL orders**: Subtracts all FILLED SELL orders (including STOP_LOSS/TAKE_PROFIT)
3. **Net quantity**: `max(filled_buy_qty - filled_sell_qty, 0)`
4. **Portfolio value**: `net_quantity * current_price`

**What it does NOT include**:
- Balances from manual deposits/transfers
- Balances from orders executed outside the system
- Open (pending) orders
- Balances that existed before the system started tracking orders

### Portfolio Tab Calculation

The Portfolio tab uses **actual exchange balances** from Crypto.com API:

1. **Source**: `portfolio_cache.py` fetches balances from Crypto.com API
2. **Calculation**: Uses `market_value` from API or calculates `balance * current_price`
3. **Includes**: ALL balances in the exchange account, regardless of source

## The Discrepancy

When there's a mismatch:
- **Risk check** sees: Only filled orders tracked in the system → lower value
- **Portfolio tab** sees: All actual balances from exchange → higher value

This happens when:
- Manual deposits were made
- Orders were executed outside the system
- Historical balances existed before order tracking started
- Open orders should be counted but aren't

## Solution: Enhanced Logging

Added detailed logging for CRO_USDT (and variants) in `calculate_portfolio_value_for_symbol`:

### Log Output Includes:

1. **Filled orders breakdown**:
   - Filled BUY orders count and details (order_id, quantity, price, status, role)
   - Filled SELL orders count and details
   - Net quantity calculation

2. **Open orders**:
   - Count of pending BUY orders
   - Total value of open BUY orders (quantity × price)

3. **Exchange balances**:
   - Actual balances from `portfolio_balances` table
   - USD value of each balance entry

4. **Final calculation**:
   - `filled_buy_qty`, `filled_sell_qty`, `net_qty`
   - `current_price`, `portfolio_value_usd`
   - `open_buy_orders_count`, `open_buy_orders_value`
   - `exchange_balance_usd`

### Example Log Entry

```
[RISK_PORTFOLIO_CHECK] symbol=CRO_USDT 
filled_buy_qty=12345.67890000 filled_sell_qty=0.00000000 net_qty=12345.67890000 
current_price=0.2845 portfolio_value_usd=3513.85 
open_buy_orders_count=2 open_buy_orders_value=567.89 
exchange_balance_usd=3513.85 
buy_orders=5 sell_orders=0
```

## Files Changed

1. **backend/app/services/order_position_service.py**:
   - Enhanced `calculate_portfolio_value_for_symbol` with detailed CRO logging
   - Logs filled orders, open orders, and exchange balances

2. **backend/app/services/signal_monitor.py**:
   - Added logging in risk check for CRO symbols
   - Logs trade_amount, limit_value, and check result

## Next Steps

1. **Monitor logs** for CRO_USDT to see the breakdown
2. **Compare** the logged values with Portfolio tab
3. **Identify** the source of the discrepancy:
   - If `exchange_balance_usd` matches Portfolio tab but `portfolio_value_usd` doesn't → missing filled orders
   - If `open_buy_orders_value` is significant → should open orders be included?
   - If balances exist but no orders → manual deposits/transfers

## Potential Fixes (Future)

Depending on what the logs reveal:

1. **Include open orders**: Add pending BUY orders to portfolio value calculation
2. **Use exchange balances**: Switch risk check to use actual balances instead of filled orders
3. **Hybrid approach**: Use filled orders + open orders + manual balance adjustments

## Verification

After deployment, check logs for:
```
[RISK_PORTFOLIO_CHECK] symbol=CRO_USDT ...
```

This will show the complete breakdown of how the $3513.xx value is calculated.






