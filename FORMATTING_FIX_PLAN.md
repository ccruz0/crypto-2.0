# Plan to Fix Quantity/Price Formatting Violations

## Overview

This plan systematically fixes all violations of `docs/trading/crypto_com_order_formatting.md` rules.

## Fix Strategy

1. **Create helper functions** for consistent formatting (DRY principle)
2. **Fix rounding directions** based on order type and side
3. **Remove trailing zero stripping**
4. **Replace `round()` with Decimal quantization**
5. **Add instrument metadata fetching** where missing

## Implementation Order

### Phase 1: Create Helper Functions (Foundation)
**Priority**: HIGH - Needed by all other fixes
**Files**: `backend/app/services/brokers/crypto_com_trade.py`

Create centralized formatting functions:
- `normalize_price()` - Format price with correct rounding direction
- `normalize_price_for_order()` - Format price based on order side/type
- Update existing `normalize_quantity()` to ensure it follows rules (already mostly correct)

### Phase 2: Fix place_limit_order() (Most Common Path)
**Priority**: HIGH
**Files**: `backend/app/services/brokers/crypto_com_trade.py`
**Lines**: 1871-1876

**Changes**:
1. Fetch instrument metadata
2. Use `normalize_price_for_order()` helper
3. Remove `.rstrip('0').rstrip('.')` calls
4. Apply correct rounding: ROUND_DOWN for BUY, ROUND_UP for SELL

### Phase 3: Fix STOP_LIMIT Order Formatting
**Priority**: HIGH
**Files**: `backend/app/services/brokers/crypto_com_trade.py`
**Function**: `place_stop_loss_order()`
**Lines**: 2310-2415, 2462-2480

**Changes**:
1. Replace ROUND_HALF_UP with ROUND_DOWN for trigger prices
2. Replace ROUND_HALF_UP with ROUND_UP for execution prices (if SELL) or ROUND_DOWN (if BUY)
3. Remove trailing zero stripping
4. Use Decimal throughout

### Phase 4: Fix TP/SL Order Creator
**Priority**: HIGH
**Files**: `backend/app/services/tp_sl_order_creator.py`
**Lines**: 125-135, 311-321

**Changes**:
1. Replace `round()` with Decimal quantization
2. Use ROUND_UP for TAKE PROFIT prices
3. Use ROUND_DOWN for STOP LOSS trigger prices
4. Fetch instrument metadata
5. Preserve trailing zeros

### Phase 5: Fix Other Order Placement Functions
**Priority**: MEDIUM
**Files**: `backend/app/services/brokers/crypto_com_trade.py`
**Functions**: Other order placement methods

**Changes**:
1. Replace ROUND_HALF_UP with directional rounding
2. Remove trailing zero stripping
3. Use helper functions where possible

### Phase 6: Fix Exchange Sync
**Priority**: MEDIUM
**Files**: `backend/app/services/exchange_sync.py`
**Lines**: 1360, 1363

**Changes**:
1. Replace ROUND_HALF_UP with ROUND_DOWN for SL, ROUND_UP for TP
2. Ensure Decimal usage

### Phase 7: Error Retry Logic
**Priority**: MEDIUM
**Files**: `backend/app/services/brokers/crypto_com_trade.py`
**Lines**: 2787, 2931, 2936, 2952

**Changes**:
1. Replace ROUND_HALF_UP with ROUND_DOWN for quantities (already should be)
2. Replace ROUND_HALF_UP with directional rounding for prices in retry logic
3. Preserve trailing zeros even in retry variations

### Phase 8: Testing & Validation
**Priority**: HIGH
**Action Items**:
1. Add unit tests for new helper functions
2. Test with real instrument metadata
3. Verify orders pass exchange validation
4. Check logs for proper formatting

## Helper Function Specifications

### normalize_price_for_order()

```python
def normalize_price_for_order(
    self,
    symbol: str,
    price: float,
    side: str,  # "BUY" or "SELL"
    order_type: str = "LIMIT",  # "LIMIT", "TAKE_PROFIT", "STOP_LOSS"
    trigger_price: bool = False  # True for trigger prices, False for execution prices
) -> str:
    """
    Normalize price according to docs/trading/crypto_com_order_formatting.md
    
    Rules:
    - BUY LIMIT: ROUND_DOWN
    - SELL LIMIT: ROUND_UP
    - TAKE PROFIT: ROUND_UP
    - STOP LOSS trigger: ROUND_DOWN
    - Always preserve trailing zeros
    - Fetch instrument metadata
    """
```

### normalize_price() (Simpler version)

```python
def normalize_price(
    self,
    symbol: str,
    price: float,
    rounding: str  # "ROUND_DOWN" or "ROUND_UP"
) -> str:
    """
    Normalize price with specified rounding direction.
    Fetches instrument metadata and formats accordingly.
    """
```

## Testing Strategy

1. **Unit Tests**: Test helper functions with known inputs
2. **Integration Tests**: Test full order placement flow
3. **Manual Verification**: Check logs for properly formatted values
4. **Exchange Validation**: Verify orders are accepted (dry-run first)

## Rollout Plan

1. ✅ Create helper functions
2. ✅ Fix place_limit_order() (most common)
3. ✅ Fix place_stop_loss_order()
4. ✅ Fix tp_sl_order_creator.py
5. ✅ Fix other functions
6. ✅ Add tests
7. ✅ Deploy with dry-run verification
8. ✅ Monitor for order rejections
9. ✅ Enable live trading after validation

## Risk Mitigation

- All fixes should be backward compatible
- Test in dry-run mode first
- Add extensive logging to verify formatting
- Monitor for "Invalid quantity format" and "Invalid price" errors
- Have rollback plan ready
