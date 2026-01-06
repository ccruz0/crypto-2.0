# Crypto.com Exchange Order Formatting Specification

**Version:** 1.0  
**Last Updated:** 2025-01-02  
**Status:** Authoritative Reference

---

## A. Why This Exists

### Problem Statement

This document exists to prevent recurring order failures caused by incorrect decimal rounding, precision mismatches, and malformed payloads sent to Crypto.com Exchange. These failures manifest as:

1. **Error 213: "Invalid quantity format"** - Quantity precision doesn't match instrument requirements
2. **Error 10004: "Invalid price"** - Price precision exceeds allowed decimal places or doesn't align with tick_size
3. **Order rejection** - Exchange rejects orders due to scientific notation, trailing zeros, or incorrect rounding direction
4. **Precision drift** - Binary float arithmetic causes cumulative rounding errors across multiple calculations

### Root Causes

- Inconsistent rounding directions (BUY vs SELL, LIMIT vs MARKET)
- Missing or incorrect instrument metadata (tick_size, step_size, decimals)
- Using binary floats instead of Decimal for final formatting
- Fallback precision logic that doesn't match actual exchange requirements
- Lack of centralized formatting rules across strategies and services

### Authority

**This document is the authoritative reference** for all Crypto.com Exchange order formatting and rounding. All code that generates order prices, quantities, or payloads MUST follow these rules. When in doubt, refer to this document.

---

## B. Definitions

### Core Precision Terms

- **`price_precision`** (or `price_decimals`): Number of decimal places allowed for PRICE values
  - Example: `price_decimals=2` means prices can have at most 2 decimal places (e.g., `123.45`)
  - Source: Crypto.com `get-instruments` API response field `price_decimals`

- **`quantity_precision`** (or `quantity_decimals`): Number of decimal places allowed for QUANTITY values
  - Example: `quantity_decimals=8` means quantities can have at most 8 decimal places (e.g., `0.12345678`)
  - Source: Crypto.com `get-instruments` API response field `quantity_decimals`

- **`tick_size`** (or `price_tick_size`): Minimum price increment allowed
  - Example: `price_tick_size=0.01` means prices must be multiples of 0.01
  - If `tick_size=0.01`, valid prices are: `100.00`, `100.01`, `100.02` (not `100.005`)
  - Source: Crypto.com `get-instruments` API response field `price_tick_size`
  - **Relationship**: `tick_size` determines `price_precision`, but they are not always equivalent

- **`step_size`** (or `qty_tick_size`): Minimum quantity increment allowed
  - Example: `qty_tick_size=0.0001` means quantities must be multiples of 0.0001
  - If `step_size=0.0001`, valid quantities are: `1.0000`, `1.0001`, `1.0002` (not `1.00005`)
  - Source: Crypto.com `get-instruments` API response field `qty_tick_size`
  - **Relationship**: `step_size` determines `quantity_precision`, but they are not always equivalent

- **`min_qty`**: Minimum order quantity allowed
  - Example: `min_qty=0.0001` means orders must be at least 0.0001 units
  - Source: Crypto.com `get-instruments` API response field `min_quantity` (if available)

- **`min_notional`**: Minimum order value in quote currency (e.g., USD, USDT)
  - Example: `min_notional=10.0` means order value must be at least $10.00
  - Source: Crypto.com `get-instruments` API response field `min_notional` (if available)

### Rounding Directions

- **ROUND_DOWN** (floor): Round towards zero (never exceed the original value)
  - Example: `1.999` → `1.99` (with 2 decimals, ROUND_DOWN)
  - Use: BUY LIMIT prices, quantities, STOP LOSS triggers

- **ROUND_UP** (ceil): Round away from zero (never undershoot the original value)
  - Example: `1.001` → `1.01` (with 2 decimals, ROUND_UP)
  - Use: SELL LIMIT prices, TAKE PROFIT prices

- **ROUND_HALF_UP**: Round to nearest, ties round up
  - Example: `1.005` → `1.01` (with 2 decimals, ROUND_HALF_UP)
  - **NOT RECOMMENDED** for order prices (use directional rounding instead)

---

## C. Canonical Rules (MUST)

### Rule 1: Use Decimal, Never Binary Floats

**MUST:** Use Python's `decimal.Decimal` for all price and quantity calculations and formatting.

```python
# ✅ CORRECT
from decimal import Decimal
price_decimal = Decimal(str(price))
qty_decimal = Decimal(str(qty))

# ❌ WRONG
price_float = float(price)  # Causes precision loss
qty_float = round(qty, 8)   # Binary float rounding
```

**Rationale:** Binary floats introduce precision errors. Decimal preserves exact decimal representation.

### Rule 2: Quantize to tick_size/step_size

**MUST:** Always quantize prices to `tick_size` and quantities to `step_size` before formatting.

```python
# ✅ CORRECT - Price quantization
tick_decimal = Decimal(str(price_tick_size))
price_decimal = (price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_decimal

# ✅ CORRECT - Quantity quantization
step_decimal = Decimal(str(qty_tick_size))
qty_decimal = (qty_decimal / step_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_decimal
```

**Rationale:** Exchange requires values to be exact multiples of tick_size/step_size.

### Rule 3: Rounding Direction by Order Type

**MUST:** Apply the following rounding directions:

| Order Type | Field | Rounding Direction | Rationale |
|------------|-------|-------------------|-----------|
| BUY LIMIT | Price | ROUND_DOWN | Never exceed intended buy price |
| SELL LIMIT | Price | ROUND_UP | Never undershoot intended sell price |
| STOP LOSS | Trigger Price | ROUND_DOWN | Conservative trigger (don't exceed) |
| TAKE PROFIT | Price | ROUND_UP | Ensure profit target is met |
| All Orders | Quantity | ROUND_DOWN | Never exceed available balance |

**Implementation:**

```python
from decimal import Decimal, ROUND_DOWN, ROUND_UP

# BUY LIMIT price
buy_price = (price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_decimal

# SELL LIMIT price
sell_price = (price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_UP) * tick_decimal

# Quantity (always ROUND_DOWN)
qty = (qty_decimal / step_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_decimal
```

### Rule 4: String Output with Exact Decimals

**MUST:** Format final values as strings with exact decimal places required by precision (no scientific notation, preserve trailing zeros).

```python
# ✅ CORRECT
price_str = f"{price_decimal:.{price_decimals}f}"  # e.g., "123.45" for 2 decimals
qty_str = f"{qty_decimal:.{quantity_decimals}f}"    # e.g., "0.12345678" for 8 decimals

# ❌ WRONG
price_str = str(price_decimal)                      # May use scientific notation
qty_str = f"{qty_decimal:.8f}".rstrip('0')         # Strips trailing zeros (exchange may require them)
```

**Rationale:** Exchange API expects exact format. Scientific notation and missing trailing zeros cause rejections.

### Rule 5: Always Fetch Instrument Metadata

**MUST:** Fetch instrument metadata from Crypto.com `get-instruments` endpoint before formatting orders.

**Endpoint:** `https://api.crypto.com/exchange/v1/public/get-instruments`

**Required Fields:**
- `instrument_name` (or `symbol`)
- `price_decimals`
- `price_tick_size`
- `quantity_decimals`
- `qty_tick_size`
- `min_quantity` (if available)
- `min_notional` (if available)

**Fallback:** If instrument metadata is unavailable, use conservative fallback precision (see Rule 6).

### Rule 6: Fallback Precision (When Metadata Unavailable)

**MUST:** Use these fallback precision values when instrument metadata cannot be fetched:

| Quantity Range | Precision | Tick Size | Example |
|----------------|-----------|-----------|---------|
| `qty >= 1` | 2 decimals | `0.01` | `1.23` |
| `0.001 <= qty < 1` | 4 decimals | `0.0001` | `0.1234` |
| `qty < 0.001` | 8 decimals | `0.00000001` | `0.12345678` |

| Price Range | Precision | Tick Size | Example |
|-------------|-----------|-----------|---------|
| `price >= 100` | 2 decimals | `0.01` | `123.45` |
| `1 <= price < 100` | 4 decimals | `0.0001` | `12.3456` |
| `price < 1` | 4 decimals | `0.0001` | `0.1234` |

**Note:** Fallback precision is a last resort. Always prefer instrument metadata.

### Examples: Before/After Formatting

#### Example 1: BUY LIMIT Order (BTC_USDT)

**Input:**
- Symbol: `BTC_USDT`
- Intended price: `43250.123456`
- Instrument metadata: `price_decimals=2`, `price_tick_size=0.01`

**Processing:**
```python
price_decimal = Decimal("43250.123456")
tick_decimal = Decimal("0.01")
# Round DOWN (BUY LIMIT)
price_quantized = (price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_decimal
# Result: Decimal("43250.12")
price_str = f"{price_quantized:.2f}"
# Result: "43250.12"
```

**Output:** `"43250.12"` ✅

---

#### Example 2: SELL LIMIT Order (ETH_USDT)

**Input:**
- Symbol: `ETH_USDT`
- Intended price: `2345.6789`
- Instrument metadata: `price_decimals=2`, `price_tick_size=0.01`

**Processing:**
```python
price_decimal = Decimal("2345.6789")
tick_decimal = Decimal("0.01")
# Round UP (SELL LIMIT)
price_quantized = (price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_UP) * tick_decimal
# Result: Decimal("2345.68")
price_str = f"{price_quantized:.2f}"
# Result: "2345.68"
```

**Output:** `"2345.68"` ✅

---

#### Example 3: Quantity Formatting (DOGE_USDT)

**Input:**
- Symbol: `DOGE_USDT`
- Calculated quantity: `1234.56789012`
- Instrument metadata: `quantity_decimals=8`, `qty_tick_size=0.00000001`

**Processing:**
```python
qty_decimal = Decimal("1234.56789012")
step_decimal = Decimal("0.00000001")
# Round DOWN (quantity)
qty_quantized = (qty_decimal / step_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_decimal
# Result: Decimal("1234.56789012")
qty_str = f"{qty_quantized:.8f}"
# Result: "1234.56789012"
```

**Output:** `"1234.56789012"` ✅

---

#### Example 4: Low-Price Coin (ALGO_USDT)

**Input:**
- Symbol: `ALGO_USDT`
- Intended price: `0.123456789`
- Instrument metadata: `price_decimals=4`, `price_tick_size=0.0001`

**Processing:**
```python
price_decimal = Decimal("0.123456789")
tick_decimal = Decimal("0.0001")
# Round UP (SELL LIMIT)
price_quantized = (price_decimal / tick_decimal).quantize(Decimal('1'), rounding=ROUND_UP) * tick_decimal
# Result: Decimal("0.1235")
price_str = f"{price_quantized:.4f}"
# Result: "0.1235"
```

**Output:** `"0.1235"` ✅

---

## D. Symbol-by-Symbol Table

### Instrument Metadata Source

Instrument metadata is fetched from Crypto.com Exchange API:

**Endpoint:** `GET https://api.crypto.com/exchange/v1/public/get-instruments`

**Response Structure:**
```json
{
  "result": {
    "instruments": [
      {
        "instrument_name": "BTC_USDT",
        "base_currency": "BTC",
        "quote_currency": "USDT",
        "price_decimals": 2,
        "price_tick_size": "0.01",
        "quantity_decimals": 6,
        "qty_tick_size": "0.000001",
        "min_quantity": "0.0001",
        "min_notional": "10.0"
      }
    ]
  }
}
```

### Current Implementation

The codebase fetches instrument metadata in multiple locations:

1. **`backend/app/services/brokers/crypto_com_trade.py`**
   - Lines 1249-1261: MARKET SELL order quantity formatting
   - Lines 2144-2160: STOP_LIMIT order price formatting
   - Lines 2744-2760: Additional order formatting
   - Lines 2968-2984: Additional order formatting
   - Line 3677: Public `get-instruments` method

2. **`backend/app/services/tp_sl_order_creator.py`**
   - TP/SL order creation with precision handling

### Symbol Table (To Be Populated)

**TODO:** This table should be populated by:
1. Fetching all instruments from `get-instruments` endpoint
2. Caching the results in a database or config file
3. Updating this table with actual values

| Symbol | Base | Quote | price_decimals | price_tick_size | quantity_decimals | qty_tick_size | min_qty | min_notional | Rounding Policy |
|--------|------|-------|----------------|-----------------|-------------------|---------------|---------|--------------|-----------------|
| BTC_USDT | BTC | USDT | 2 | 0.01 | 6 | 0.000001 | 0.0001 | 10.0 | Price: ROUND_DOWN (BUY), ROUND_UP (SELL)<br>Qty: ROUND_DOWN |
| ETH_USDT | ETH | USDT | 2 | 0.01 | 4 | 0.0001 | 0.001 | 10.0 | Price: ROUND_DOWN (BUY), ROUND_UP (SELL)<br>Qty: ROUND_DOWN |
| DOT_USDT | DOT | USDT | 4 | 0.0001 | 2 | 0.01 | 0.1 | 10.0 | Price: ROUND_DOWN (BUY), ROUND_UP (SELL)<br>Qty: ROUND_DOWN |
| ALGO_USDT | ALGO | USDT | 4 | 0.0001 | 2 | 0.01 | 1.0 | 10.0 | Price: ROUND_DOWN (BUY), ROUND_UP (SELL)<br>Qty: ROUND_DOWN |
| DOGE_USDT | DOGE | USDT | 8 | 0.00000001 | 8 | 0.00000001 | 1.0 | 10.0 | Price: ROUND_DOWN (BUY), ROUND_UP (SELL)<br>Qty: ROUND_DOWN |

**Note:** The above values are examples. **Actual values must be fetched from the API.**

### How to Generate Symbol Table Automatically

**Recommended Approach:**

1. Create a script or service method that:
   - Fetches all instruments from `get-instruments` endpoint
   - Parses and stores metadata in a database or JSON file
   - Updates this documentation table periodically

2. **Implementation Location:**
   - Add to `backend/app/services/brokers/crypto_com_trade.py` as a method: `get_all_instruments_metadata()`
   - Cache results in Redis or database with TTL (e.g., 1 hour)
   - Create a management command: `python manage.py update_instrument_metadata`

3. **Example Code:**
```python
def get_all_instruments_metadata(self) -> Dict[str, Dict]:
    """Fetch and cache all instrument metadata from Crypto.com."""
    url = f"{REST_BASE}/public/get-instruments"
    response = http_get(url, timeout=10)
    instruments = {}
    for inst in response.get("result", {}).get("instruments", []):
        symbol = inst.get("instrument_name", "").upper()
        instruments[symbol] = {
            "base": inst.get("base_currency", ""),
            "quote": inst.get("quote_currency", ""),
            "price_decimals": inst.get("price_decimals"),
            "price_tick_size": inst.get("price_tick_size"),
            "quantity_decimals": inst.get("quantity_decimals"),
            "qty_tick_size": inst.get("qty_tick_size"),
            "min_quantity": inst.get("min_quantity"),
            "min_notional": inst.get("min_notional"),
        }
    return instruments
```

---

## E. Implementation Reference

### Code Locations

#### Primary Order Formatting

1. **`backend/app/services/brokers/crypto_com_trade.py`**
   - **Line 1239-1301:** MARKET SELL order quantity formatting
     - Fetches instrument metadata
     - Uses Decimal for precision
     - Applies ROUND_DOWN for quantities
     - Fallback precision logic
   
   - **Line 2160-2200:** STOP_LIMIT order price formatting
     - Fetches instrument metadata
     - Uses Decimal for precision
     - Applies ROUND_HALF_UP (should be changed to ROUND_DOWN/ROUND_UP based on order side)
     - Fallback precision logic
   
   - **Line 1590-1640:** Error 213 retry logic with multiple precision levels
     - Tries different precision levels when order fails
     - Uses Decimal for all calculations

2. **`backend/app/services/tp_sl_order_creator.py`**
   - TAKE PROFIT and STOP LOSS order creation
   - Should follow same formatting rules

#### Instrument Metadata Fetching

- **`backend/app/services/brokers/crypto_com_trade.py`**
  - **Line 3677:** `get_instruments()` method
  - **Lines 1249, 2144, 2744, 2968:** Inline instrument metadata fetching

### How to Use This Doc When Coding

**Checklist for implementing order formatting:**

1. ✅ **Import Decimal:**
   ```python
   from decimal import Decimal, ROUND_DOWN, ROUND_UP
   ```

2. ✅ **Fetch instrument metadata:**
   ```python
   inst_metadata = fetch_instrument_metadata(symbol)
   price_decimals = inst_metadata.get("price_decimals")
   price_tick_size = Decimal(inst_metadata.get("price_tick_size", "0.01"))
   quantity_decimals = inst_metadata.get("quantity_decimals", 2)
   qty_tick_size = Decimal(inst_metadata.get("qty_tick_size", "0.01"))
   ```

3. ✅ **Convert to Decimal:**
   ```python
   price_decimal = Decimal(str(price))
   qty_decimal = Decimal(str(qty))
   ```

4. ✅ **Quantize with correct rounding:**
   ```python
   # Price (BUY: ROUND_DOWN, SELL: ROUND_UP)
   rounding = ROUND_DOWN if side == "BUY" else ROUND_UP
   price_quantized = (price_decimal / price_tick_size).quantize(Decimal('1'), rounding=rounding) * price_tick_size
   
   # Quantity (always ROUND_DOWN)
   qty_quantized = (qty_decimal / qty_tick_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * qty_tick_size
   ```

5. ✅ **Format as string with exact decimals:**
   ```python
   price_str = f"{price_quantized:.{price_decimals}f}"
   qty_str = f"{qty_quantized:.{quantity_decimals}f}"
   ```

6. ✅ **Validate before sending:**
   ```python
   # Check min_qty and min_notional
   if qty_quantized < Decimal(inst_metadata.get("min_quantity", "0")):
       raise ValueError(f"Quantity {qty_quantized} below minimum {inst_metadata['min_quantity']}")
   
   notional = price_quantized * qty_quantized
   if notional < Decimal(inst_metadata.get("min_notional", "0")):
       raise ValueError(f"Notional {notional} below minimum {inst_metadata['min_notional']}")
   ```

7. ✅ **Log order preview:**
   ```python
   logger.info(f"Order preview for {symbol}: price={price} -> {price_str}, qty={qty} -> {qty_str}")
   ```

---

## F. Test and Validation

### Unit Tests

**Recommended test cases:**

#### Test 1: Price Formatting for High-Value Coin (BTC)

```python
def test_btc_price_formatting():
    """Test BTC_USDT price formatting with 2 decimals, 0.01 tick_size."""
    symbol = "BTC_USDT"
    price = Decimal("43250.123456")
    price_decimals = 2
    price_tick_size = Decimal("0.01")
    
    # BUY LIMIT (ROUND_DOWN)
    buy_price = (price / price_tick_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * price_tick_size
    buy_price_str = f"{buy_price:.{price_decimals}f}"
    assert buy_price_str == "43250.12"
    
    # SELL LIMIT (ROUND_UP)
    sell_price = (price / price_tick_size).quantize(Decimal('1'), rounding=ROUND_UP) * price_tick_size
    sell_price_str = f"{sell_price:.{price_decimals}f}"
    assert sell_price_str == "43250.13"
```

#### Test 2: Quantity Formatting for Low-Value Coin (DOGE)

```python
def test_doge_quantity_formatting():
    """Test DOGE_USDT quantity formatting with 8 decimals, 0.00000001 step_size."""
    symbol = "DOGE_USDT"
    qty = Decimal("1234.56789012345")
    quantity_decimals = 8
    qty_tick_size = Decimal("0.00000001")
    
    # Always ROUND_DOWN
    qty_quantized = (qty / qty_tick_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * qty_tick_size
    qty_str = f"{qty_quantized:.{quantity_decimals}f}"
    assert qty_str == "1234.56789012"
```

#### Test 3: Low-Price Coin (ALGO)

```python
def test_algo_price_formatting():
    """Test ALGO_USDT price formatting with 4 decimals, 0.0001 tick_size."""
    symbol = "ALGO_USDT"
    price = Decimal("0.123456789")
    price_decimals = 4
    price_tick_size = Decimal("0.0001")
    
    # SELL LIMIT (ROUND_UP)
    sell_price = (price / price_tick_size).quantize(Decimal('1'), rounding=ROUND_UP) * price_tick_size
    sell_price_str = f"{sell_price:.{price_decimals}f}"
    assert sell_price_str == "0.1235"
```

#### Test 4: Rounding Direction Correctness

```python
def test_rounding_directions():
    """Verify rounding directions match specification."""
    value = Decimal("1.999")
    tick = Decimal("0.01")
    
    # BUY LIMIT: ROUND_DOWN
    buy = (value / tick).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick
    assert buy == Decimal("1.99")  # Never exceed
    
    # SELL LIMIT: ROUND_UP
    sell = (value / tick).quantize(Decimal('1'), rounding=ROUND_UP) * tick
    assert sell == Decimal("2.00")  # Never undershoot
```

#### Test 5: No Scientific Notation

```python
def test_no_scientific_notation():
    """Ensure formatted values never use scientific notation."""
    price = Decimal("0.00001234")
    price_decimals = 8
    price_str = f"{price:.{price_decimals}f}"
    
    assert "e" not in price_str.lower()  # No scientific notation
    assert price_str == "0.00001234"
```

### Runtime Validation Checklist

**Before sending order to exchange:**

1. ✅ **Verify formatted payload matches instrument constraints:**
   ```python
   # Check price precision
   assert len(price_str.split('.')[-1]) <= price_decimals
   
   # Check quantity precision
   assert len(qty_str.split('.')[-1]) <= quantity_decimals
   
   # Check tick_size alignment
   price_decimal = Decimal(price_str)
   assert (price_decimal % price_tick_size) == 0, f"Price {price_str} not aligned to tick_size {price_tick_size}"
   
   # Check step_size alignment
   qty_decimal = Decimal(qty_str)
   assert (qty_decimal % qty_tick_size) == 0, f"Quantity {qty_str} not aligned to step_size {qty_tick_size}"
   ```

2. ✅ **Log structured order preview:**
   ```python
   logger.info(f"""
   Order Preview for {symbol}:
     Raw Price: {price} (type: {type(price).__name__})
     Formatted Price: {price_str} (decimals: {price_decimals}, tick_size: {price_tick_size})
     Raw Quantity: {qty} (type: {type(qty).__name__})
     Formatted Quantity: {qty_str} (decimals: {quantity_decimals}, step_size: {qty_tick_size})
     Notional: {Decimal(price_str) * Decimal(qty_str)}
     Min Notional: {min_notional}
     Valid: {Decimal(price_str) * Decimal(qty_str) >= Decimal(min_notional)}
   """)
   ```

3. ✅ **Validate min_qty and min_notional:**
   ```python
   if qty_decimal < Decimal(min_qty):
       raise ValueError(f"Quantity {qty_str} below minimum {min_qty}")
   
   notional = price_decimal * qty_decimal
   if notional < Decimal(min_notional):
       raise ValueError(f"Notional {notional} below minimum {min_notional}")
   ```

---

## Appendix: Common Errors and Solutions

### Error 213: "Invalid quantity format"

**Cause:** Quantity precision doesn't match instrument requirements.

**Solution:**
1. Fetch instrument metadata for the symbol
2. Use `quantity_decimals` and `qty_tick_size` from metadata
3. Quantize quantity to `qty_tick_size` with ROUND_DOWN
4. Format with exact `quantity_decimals` decimal places

### Error 10004: "Invalid price"

**Cause:** Price precision exceeds allowed decimal places or doesn't align with tick_size.

**Solution:**
1. Fetch instrument metadata for the symbol
2. Use `price_decimals` and `price_tick_size` from metadata
3. Quantize price to `price_tick_size` with correct rounding direction
4. Format with exact `price_decimals` decimal places

### Scientific Notation in Payload

**Cause:** Using `str(Decimal)` instead of formatted string.

**Solution:**
```python
# ❌ WRONG
price_str = str(Decimal("0.00001234"))  # May produce "1.234E-5"

# ✅ CORRECT
price_str = f"{Decimal('0.00001234'):.8f}"  # Produces "0.00001234"
```

### Trailing Zeros Stripped

**Cause:** Using `.rstrip('0')` or similar.

**Solution:**
```python
# ❌ WRONG
price_str = f"{price:.2f}".rstrip('0')  # "123.45" -> "123.45", "123.00" -> "123"

# ✅ CORRECT
price_str = f"{price:.2f}"  # "123.45" -> "123.45", "123.00" -> "123.00"
```

---

## References

- **Crypto.com Exchange API Documentation:** https://exchange-docs.crypto.com/
- **Primary Implementation:** `backend/app/services/brokers/crypto_com_trade.py`
- **TP/SL Orders:** `backend/app/services/tp_sl_order_creator.py`
- **Instrument Metadata Endpoint:** `GET /public/get-instruments`

---

**Document Maintainer:** Engineering Team  
**Review Frequency:** Quarterly or when exchange requirements change  
**Last Review Date:** 2025-01-02






