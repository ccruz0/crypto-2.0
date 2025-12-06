# Risk Level Bug Fix

## Issue Description

The `risk_level` variable was referenced in context dicts for `emit_alert()` calls, but was never defined. The check `'risk_level' in locals()` would always evaluate to False, causing the context to always have `"risk": None`.

## Root Cause

- `risk_level` variable was referenced but never defined
- Should use `risk_display` instead, which is properly defined at line 626 in `signal_monitor.py`
- `risk_display` is derived from `risk_approach.value.title()` where `risk_approach` comes from `resolve_strategy_profile()`

## Fix Applied

1. Verified that `risk_display` is correctly defined at line 626:
   ```python
   risk_display = risk_approach.value.title()
   ```

2. Ensured all context dicts use `risk_display` instead of `risk_level`

3. Verified that `_log_symbol_context()` correctly uses `risk_display` in its context dict

## Verification

- ✅ No references to `risk_level` found in codebase
- ✅ `risk_display` is properly defined and used throughout
- ✅ Context dicts correctly use `risk_display`

## Prevention

Going forward, all context dicts should use `risk_display` which is:
- Defined at line 626 in `signal_monitor.py`
- Derived from the canonical evaluator result via `resolve_strategy_profile()`
- Available in the scope where alerts are emitted

