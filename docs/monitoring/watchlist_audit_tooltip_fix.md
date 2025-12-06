# Watchlist Audit Tooltip Fix

**Date:** 2025-12-01  
**Issue:** Tooltip showing incorrect "No se requieren MAs" for scalp-aggressive strategy

## Problem

The tooltip was showing "No se requieren MAs" (No MAs required) for `scalp-aggressive` strategy, even though:
- The backend config requires `ema10: true` for `scalp-aggressive`
- The backend was correctly blocking BUY signals when price didn't meet EMA10 requirement
- The tooltip showed all BUY criteria as green (✓) but backend decision was WAIT

## Root Cause

The tooltip logic in `buildSignalCriteriaTooltip()` was only checking `ma50` and `ma200` to determine if MAs are required:

```typescript
if (!rules.maChecks?.ma50 && !rules.maChecks?.ma200) {
  lines.push(`  • No se requieren MAs`);
}
```

This missed the case where `ema10: true` but `ma50: false` and `ma200: false` (as in `scalp-aggressive`).

## Fix

### 1. Added EMA10 Check Display

When `ema10: true` but `ma50: false`, the tooltip now shows:
```
• Precio > EMA10 ✓/✗
  - Precio: $X.XX
  - EMA10: $X.XX
```

### 2. Fixed "No se requieren MAs" Logic

Changed from:
```typescript
if (!rules.maChecks?.ma50 && !rules.maChecks?.ma200) {
  lines.push(`  • No se requieren MAs`);
}
```

To:
```typescript
// Check if ANY MA is required (ema10, ma50, or ma200)
const requiresAnyMA = rules.maChecks?.ema10 || rules.maChecks?.ma50 || rules.maChecks?.ma200;

// Only show "No se requieren MAs" if NO MAs are required at all
if (!requiresAnyMA) {
  lines.push(`  • No se requieren MAs`);
}
```

### 3. Improved Blocking Criteria Display

Changed from generic "MA" to specific MA type:
- If only EMA10 is required → shows "EMA10" as blocking
- If MA50 is required → shows "MA50" as blocking
- If MA200 is required → shows "MA200" as blocking

## Files Changed

- `frontend/src/app/page.tsx`: Fixed `buildSignalCriteriaTooltip()` function

## Verification

After fix:
- Tooltip for `scalp-aggressive` now shows "Precio > EMA10" criterion
- "No se requieren MAs" only appears when ALL maChecks are false
- Blocking criteria shows specific MA type (EMA10, MA50, or MA200)

## Related Issues

This issue was discovered during the Watchlist audit. The audit tests passed because they only verified that the Signals chip matches backend decision, but didn't verify tooltip content accuracy.

## Next Steps

1. ✅ Fix deployed to AWS
2. ⏳ Add tooltip content validation to audit tests (future improvement)

## Troubleshooting

If the tooltip still shows "No se requieren MAs" after the fix:

1. **Clear browser cache**: Hard refresh (Cmd+Shift+R on Mac, Ctrl+Shift+R on Windows/Linux)
2. **Verify frontend is rebuilt**: Check that the frontend container was rebuilt with `--no-cache`
3. **Check rules object**: Verify that `PRESET_CONFIG['Scalp'].rules['Aggressive'].maChecks.ema10 === true`
4. **Verify data availability**: Ensure `ema10` and `currentPrice` are available when building the tooltip

The fix ensures that:
- When `ema10: true` and `ma50: false`, the tooltip shows "Precio > EMA10" criterion
- "No se requieren MAs" only appears when ALL maChecks are false
- Blocking criteria shows specific MA type (EMA10, MA50, or MA200)

