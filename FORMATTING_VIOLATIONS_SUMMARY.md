# Code Violations of Quantity/Price Formatting Documentation

## Summary

The codebase has multiple violations of the formatting rules documented in `docs/trading/crypto_com_order_formatting.md`. This document identifies the specific violations.

## Documented Rules (from `docs/trading/crypto_com_order_formatting.md`)

### Rule 3: Rounding Direction by Order Type
- **BUY LIMIT prices**: ROUND_DOWN
- **SELL LIMIT prices**: ROUND_UP
- **STOP LOSS triggers**: ROUND_DOWN
- **TAKE PROFIT prices**: ROUND_UP
- **All Orders quantities**: ROUND_DOWN (always)
- **Note**: ROUND_HALF_UP is explicitly "NOT RECOMMENDED" for order prices

### Rule 4: String Output with Exact Decimals
- MUST format with exact decimal places
- MUST preserve trailing zeros
- MUST avoid scientific notation
- Example: `"123.00"` not `"123"`, `"0.12345678"` not `"0.12345678"` with zeros stripped

### Rule 1: Use Decimal, Never Binary Floats
- MUST use `decimal.Decimal` for calculations
- MUST NOT use Python's `round()` function (uses binary floats)

## Violations Found

### 1. Wrong Rounding Direction (ROUND_HALF_UP instead of Directional Rounding)

**Location**: Multiple files using `ROUND_HALF_UP` instead of proper directional rounding

**Files affected**:
- `backend/app/services/brokers/crypto_com_trade.py` (19 instances)
- `backend/app/services/tp_sl_order_creator.py` (2 instances)
- `backend/app/services/exchange_sync.py` (2 instances)

**Examples**:

```python
# ❌ WRONG - Line 2315 in crypto_com_trade.py
price_decimal = (price_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal
# Should use ROUND_DOWN for BUY, ROUND_UP for SELL based on side parameter

# ❌ WRONG - Line 134 in tp_sl_order_creator.py
tp_price_decimal = (tp_price_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal
# Should use ROUND_UP for TAKE PROFIT (per Rule 3)

# ❌ WRONG - Line 320 in tp_sl_order_creator.py
sl_price_decimal = (sl_price_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal
# Should use ROUND_DOWN for STOP LOSS (per Rule 3)
```

**Impact**: Orders may be placed at incorrect prices, potentially causing:
- BUY orders placed slightly higher than intended
- SELL orders placed slightly lower than intended
- TAKE PROFIT targets not guaranteed to be met
- STOP LOSS triggers potentially activating prematurely

### 2. Trailing Zeros Removed (Violates Rule 4)

**Location**: `backend/app/services/brokers/crypto_com_trade.py`, `place_limit_order()` method

```python
# ❌ WRONG - Lines 1871-1876
if price >= 100:
    price_str = f"{price:.2f}" if price % 1 == 0 else f"{price:.4f}".rstrip('0').rstrip('.')
elif price >= 1:
    price_str = f"{price:.4f}".rstrip('0').rstrip('.')
else:
    price_str = f"{price:.8f}".rstrip('0').rstrip('.')
```

**Should be**: Preserve trailing zeros as per Rule 4
```python
# ✅ CORRECT
price_str = f"{price_decimal:.{price_decimals}f}"  # Preserves trailing zeros
```

**Impact**: Exchange may reject orders if trailing zeros are required for validation

### 3. Using `round()` Instead of Decimal (Violates Rule 1)

**Location**: `backend/app/services/tp_sl_order_creator.py`

```python
# ❌ WRONG - Lines 125-128, 311-314
if entry_price >= 100:
    tp_price = round(tp_price, 2)  # Uses binary float rounding
elif entry_price >= 1:
    tp_price = round(tp_price, 6)  # Uses binary float rounding
```

**Should be**: Use Decimal quantization
```python
# ✅ CORRECT
tp_price_decimal = Decimal(str(tp_price))
# Then quantize with proper rounding direction
```

**Impact**: Precision loss due to binary float arithmetic, cumulative rounding errors

### 4. Missing Instrument Metadata Fetching in Some Places

**Location**: `backend/app/services/brokers/crypto_com_trade.py`, `place_limit_order()`

The `place_limit_order()` method doesn't fetch instrument metadata before formatting prices, relying on fallback precision logic instead of fetching actual `price_decimals` and `price_tick_size` from the exchange.

**Impact**: May use incorrect precision, leading to order rejections

## Frontend Formatting (Lower Priority - Display Only)

The frontend `formatNumber()` function in `frontend/src/utils/formatting.ts` uses:
- `toFixed()` (JavaScript binary float formatting)
- Trailing zero removal (`.replace(/0+$/, '')`)

**Status**: This is for **display purposes only**. However, if values from the frontend are sent directly to the backend without proper conversion, they could cause issues.

## Recommended Fixes

1. **Replace all `ROUND_HALF_UP` with directional rounding**:
   - BUY LIMIT: ROUND_DOWN
   - SELL LIMIT: ROUND_UP
   - TAKE PROFIT: ROUND_UP
   - STOP LOSS: ROUND_DOWN
   - Quantities: ROUND_DOWN (already correct in `normalize_quantity()`)

2. **Remove trailing zero stripping**:
   - Use `f"{value:.{decimals}f}"` format
   - Never use `.rstrip('0')` or `.rstrip('.')` on formatted order values

3. **Replace `round()` with Decimal quantization**:
   - Convert to Decimal: `Decimal(str(value))`
   - Quantize with proper rounding direction
   - Format as string with exact decimals

4. **Fetch instrument metadata before formatting**:
   - Always fetch `price_decimals`, `price_tick_size`, `quantity_decimals`, `qty_tick_size`
   - Only use fallback precision when metadata is unavailable

## Priority

**High Priority**:
- Fix rounding direction violations (violates core trading logic)
- Fix trailing zero removal (can cause order rejections)

**Medium Priority**:
- Replace `round()` with Decimal (precision issues)

**Low Priority**:
- Frontend formatting (display only, but verify no direct usage in orders)
