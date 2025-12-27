# Documentation Update Summary

**Date:** 2025-12-24  
**Task:** Update internal documentation to match NEW canonical logic for alerts and orders

## Summary

Updated all documentation to reflect the canonical logic where:
- Alert throttling is fixed at 60 seconds (not configurable)
- Throttling is per (symbol, side) - BUY and SELL are independent
- Config changes trigger immediate bypass (one-time per side)
- Orders are created only after successful alert (no re-checking price change)
- Price gate uses `baseline_price` from last sent message (not last order)

---

## Modified Files

### 1. Primary Canonical Document
- **`docs/ALERTAS_Y_ORDENES_NORMAS.md`** ✅
  - Already correctly documents canonical logic
  - Fixed 60 seconds throttling
  - Per (symbol, side) granularity
  - Config change immediate bypass
  - Independent BUY/SELL sides
  - Field naming consistency (baseline_price, last_sent_at, allow_immediate_after_config_change)

### 2. Order Blocking Conditions
- **`CONDICIONES_BLOQUEO_COMPRAS.md`** ✅
  - Removed reference to "price change from last order" (deprecated)
  - Updated checklist to reference alert throttling instead
  - Updated summary table to mark deprecated conditions
  - Added reference to canonical document

### 3. Diagnostic Documentation
- **`docs/monitoring/LDO_ALERTA_ORDEN_DIAGNOSTICO.md`** ✅
  - Updated throttle section to reflect fixed 60 seconds
  - Removed references to configurable `alert_cooldown_minutes`
  - Updated to use `baseline_price` terminology
  - Updated checklist items

### 4. Business Rules Validation
- **`docs/monitoring/business_rules_validation.md`** ✅
  - Updated throttling section to reflect canonical logic
  - Added note about deprecated `alert_cooldown_minutes` field
  - Added reference to canonical document

### 5. Test Documentation
- **`docs/monitoring/ADA_SELL_ALERT_FIX_SUMMARY.md`** ✅
  - Marked "SELL after BUY resets throttle" test as deprecated
  - Added note about independent sides

---

## Key Changes Made

### 1. Alert Throttling Logic
- **BEFORE**: Configurable cooldown (`alert_cooldown_minutes`, default 5 minutes)
- **AFTER**: Fixed 60 seconds (not configurable)
- **Documented in**: All affected docs updated

### 2. Price Change Verification
- **BEFORE**: Some docs referenced "price change from last order"
- **AFTER**: Price change verified relative to `baseline_price` from last sent message
- **Documented in**: CONDICIONES_BLOQUEO_COMPRAS.md, LDO_ALERTA_ORDEN_DIAGNOSTICO.md

### 3. Side Independence
- **BEFORE**: Some docs mentioned "change of side resets throttling"
- **AFTER**: BUY and SELL are completely independent (per symbol, side)
- **Documented in**: ADA_SELL_ALERT_FIX_SUMMARY.md (marked deprecated), main doc already correct

### 4. Config Change Immediate Bypass
- **BEFORE**: Not clearly documented
- **AFTER**: Fully documented with examples in canonical doc
- **Documented in**: ALERTAS_Y_ORDENES_NORMAS.md (already present)

### 5. Field Naming Consistency
- **BEFORE**: Mixed usage of `last_price`/`baseline_price`, `last_time`/`last_sent_at`
- **AFTER**: Documentation uses canonical names with code alias notes
- **Documented in**: ALERTAS_Y_ORDENES_NORMAS.md (mapping section)

---

## Documentation Consistency Checklist

- [x] Alert throttling fixed to 60s per (symbol, side)
- [x] Price gate uses `baseline_price` (not last order price)
- [x] Config-change immediate bypass documented
- [x] Orders only after successful alert (no re-checking price)
- [x] TP/SL percent fields documented
- [x] Independent BUY/SELL sides (no mutual reset)
- [x] Field naming consistency (baseline_price, last_sent_at, allow_immediate_after_config_change)
- [x] All deprecated terms marked or removed

---

## Verification Commands

### Check for deprecated terms
```bash
# Should show only deprecated/historical references
grep -R "alert_cooldown_minutes" docs/ --include="*.md" | grep -v "DEPRECATED\|HISTORICAL\|deprecated" || echo "✅ Only deprecated references found"

# Should show only deprecated/historical references  
grep -R "minIntervalMinutes" docs/ --include="*.md" | grep -v "DEPRECATED\|HISTORICAL\|deprecated" || echo "✅ Only deprecated references found"

# Should show only deprecated references
grep -R "change of side resets\|side change resets\|direction change resets" docs/ --include="*.md" -i | grep -v "DEPRECATED\|deprecated\|NO resetea\|independiente" || echo "✅ Only deprecated/negative references found"

# Should show only deprecated references
grep -R "5 minutes cooldown\|5 minute cooldown" docs/ --include="*.md" -i | grep -v "DEPRECATED\|deprecated\|orden\|order" || echo "✅ Only deprecated/order-related references found"

# Should show only deprecated references
grep -R "price change from last order\|price change.*last order" docs/ --include="*.md" -i | grep -v "DEPRECATED\|deprecated\|NO\|not" || echo "✅ Only deprecated/negative references found"
```

### Verify canonical document exists
```bash
# Should show the canonical document
ls -la docs/ALERTAS_Y_ORDENES_NORMAS.md && echo "✅ Canonical document exists"
```

### Check field naming consistency
```bash
# Should show canonical names in main doc
grep -E "baseline_price|last_sent_at|allow_immediate_after_config_change" docs/ALERTAS_Y_ORDENES_NORMAS.md | head -5 && echo "✅ Canonical field names used"
```

---

## Remaining Deprecated Fields in Code

**Note**: The following fields exist in the database/code but are deprecated:
- `alert_cooldown_minutes` (watchlist field) - Not used, throttling is fixed at 60s
- `ALERT_COOLDOWN_MINUTES` (code constant) - May exist but not used for throttling decisions

These are kept for backward compatibility but should not be referenced in new documentation.

---

## Next Steps

1. ✅ All documentation updated
2. ⚠️ Code may still reference deprecated fields - this is OK for backward compatibility
3. ✅ All docs now reference canonical document (`docs/ALERTAS_Y_ORDENES_NORMAS.md`)
4. ✅ Inconsistencies marked as deprecated or removed

---

## References

- **Canonical Document**: `docs/ALERTAS_Y_ORDENES_NORMAS.md`
- **Implementation**: `backend/app/services/signal_throttle.py`
- **Model**: `backend/app/models/signal_throttle.py`
