# Crypto.com Exchange: SL/TP Order Creation

This document explains how Take Profit (TP) and Stop Loss (SL) orders are created for Crypto.com Exchange, required formats, rounding rules, and how to debug common errors (308, 140001).

## Supported order types for TP/SL

- **TAKE_PROFIT_LIMIT**: Used for take-profit. Trigger and execution price are the same (TP price). Trigger condition: market price >= TP price (for SELL to close long).
- **STOP_LIMIT**: Used for stop-loss. Trigger and execution price are the same (SL price). Trigger condition: market price <= SL price (for SELL to close long).

Both use the `private/create-order` endpoint with `type` set to the order type. The exchange may also support batch/trigger endpoints; the code tries multiple parameter variants when formatting fails.

## Required fields and formats

- **instrument_name** / **symbol**: e.g. `ETH_USDT`.
- **side**: `BUY` or `SELL` (closing side: SELL for long, BUY for short).
- **type**: `TAKE_PROFIT_LIMIT` or `STOP_LIMIT`.
- **quantity**: String, decimal format. Must be quantized to the instrument’s **qty_tick_size** (step). Use **ROUND_DOWN** for quantity. No scientific notation, no commas.
- **price**: String, decimal format. Must be quantized to **price_tick_size** (tick). TAKE_PROFIT uses **ROUND_UP**; STOP_LOSS uses **ROUND_DOWN**. No scientific notation, no commas.
- **trigger_price**: String, same rules as price. For TAKE_PROFIT_LIMIT and STOP_LIMIT, trigger_price typically equals price.
- **ref_price**: Used for trigger condition display. Must match the expected format (same precision as trigger_price).
- **trigger_condition**: String, e.g. `">= 2984.41"` (TP) or `"<= 2659.37"` (SL). Spacing and comparator must match exchange expectations; the code tries variants (space, no space, omit) when needed.

Instrument metadata (**price_tick_size**, **qty_tick_size**, **min_quantity**, **price_decimals**, **quantity_decimals**) is obtained from `public/get-instruments` and cached. All numeric values are computed with **Decimal** and converted to string only at the request boundary.

## Rounding rules (tick size) and examples

- **Price**: Quantize to `price_tick_size`. TAKE_PROFIT: ROUND_UP. STOP_LOSS: ROUND_DOWN.
- **Quantity**: Quantize to `qty_tick_size`. ROUND_DOWN. Result must be >= `min_quantity`.

### Example: ETH_USDT (filled=2954.86, qty=0.0033, SL=2659.374, TP=2984.4086)

Assume `price_tick_size=0.01`, `qty_tick_size=0.001`:

| Field   | Raw        | Quantized (TP: ROUND_UP, SL: ROUND_DOWN, qty: ROUND_DOWN) | Formatted string |
|--------|------------|-----------------------------------------------------------|-------------------|
| TP price | 2984.4086 | 2984.41  | `"2984.41"` |
| SL price | 2659.374  | 2659.37  | `"2659.37"` |
| quantity | 0.0033    | 0.003    | `"0.003"`   |
| trigger_condition (TP) | 2984.4086 | 2984.41 | `">= 2984.41"` |
| trigger_condition (SL) | 2659.374  | 2659.37 | `"<= 2659.37"` |

The formatting layer is in `backend/app/core/exchange_formatting_week6.py` (e.g. `normalize_decimal_str`, `quantize_price`, `quantize_qty`, `format_trigger_condition`). The broker uses `normalize_price` / `normalize_quantity` in `crypto_com_trade.py` and aligns with these rules.

## Common failure modes

### Error 308: Invalid price format

- **Cause**: Price, trigger_price, or ref_price not in the format the exchange expects (wrong precision, scientific notation, or not aligned to tick).
- **How we prevent it**: Quantize all prices to the instrument’s **price_tick_size**; format as plain decimal strings (no scientific notation, no commas). We try several decimal-format variants and trigger_condition variants. On 308 we log `decision=FAILED reason_code=INVALID_PRICE_FORMAT` with pre-quantized and quantized values (no secrets).
- **Where to change formatting**: `backend/app/core/exchange_formatting_week6.py` (quantize/format helpers); `backend/app/services/brokers/crypto_com_trade.py` (`normalize_price`, `normalize_quantity`, and the 308 handling in `place_stop_loss_order` / `place_take_profit_order`).

### Error 140001: API_DISABLED

- **Meaning**: Conditional/trigger orders are disabled for this account or API key (e.g. endpoint permissions, IP allowlist, or account setting).
- **Behaviour**: We do not retry the same request (140001 is non-retryable). We log `decision=BLOCKED reason_code=EXCHANGE_API_DISABLED` and include a short operator checklist. A rate-limited Telegram alert is sent (once per 24h). Retry/circuit logic treats 140001 as non-retryable.
- **Operator steps**: Enable API trading / conditional orders for the account; check IP allowlist and sub-account permissions. See the log field `operator_action` and the in-app alert text. No amount of code change will fix 140001 without the account/API being enabled for conditional orders.

## Where in code to change formatting rules

- **Decimal formatting and quantize/validate helpers**: `backend/app/core/exchange_formatting_week6.py`
- **Broker normalization (used for TP/SL payloads)**: `backend/app/services/brokers/crypto_com_trade.py` — `normalize_price()`, `normalize_quantity()`, `_get_instrument_metadata()`
- **TP/SL creation entry points**: `backend/app/services/tp_sl_order_creator.py` — `create_take_profit_order()`, `create_stop_loss_order()`; they call `trade_client.place_take_profit_order()` and `place_stop_loss_order()`
- **Error handling and structured logs**: In `crypto_com_trade.py`, search for `reason_code=EXCHANGE_API_DISABLED` and `reason_code=INVALID_PRICE_FORMAT`
- **Retry/circuit (non-retryable 308/140001)**: `backend/app/core/retry_circuit_week5.py` — `NON_RETRYABLE_EXCHANGE_CODES`, `is_exchange_code_retryable()`, `is_retryable_error(..., exchange_code=...)`
