# Portfolio Verification Checklist

## Root Cause Explanation

**Mismatch happened because we were displaying GROSS assets while Crypto.com displays NET equity.**

Crypto.com Exchange "Portfolio balance" = NET equity (assets - borrowed), not gross assets. Our dashboard was showing gross assets as "Total Value", causing a mismatch. The fix ensures:
- "Total Value" = NET equity (matches Crypto.com exactly)
- "Gross Assets" shown separately (informational only)
- "Borrowed" shown separately (never added to totals)

## Verification Steps

### 1. Enable Diagnostic Logging
```bash
cd /Users/carloscruz/automated-trading-platform
export PORTFOLIO_DEBUG=1
# Restart backend
```

### 2. Check Backend Logs
Look for the regression guard line:
```
[PORTFOLIO_DEBUG] Portfolio summary: net=$XXXX.XX, gross=$YYYY.YY, borrowed=$ZZZZ.ZZ, pricing_source=crypto_com_api
```

Verify:
- `net` = total_usd (NET equity)
- `gross` = total_assets_usd (GROSS assets)
- `borrowed` = total_borrowed_usd (borrowed amounts)
- `pricing_source` = crypto_com_api (single source of truth)

### 3. Reload Dashboard
- Open Trading Dashboard
- Navigate to Portfolio tab
- Check "Total Value" card

### 4. Compare with Crypto.com UI
- Open Crypto.com Exchange
- Navigate to Portfolio/Balance page
- Compare "Portfolio balance" with dashboard "Total Value"

**Expected Result:**
- Difference ≤ $5 (due to rounding)
- "Total Value" (NET) should match Crypto.com "Portfolio balance"
- "Gross Assets" may differ (informational only, not used in totals)

### 5. Verify UI Labels
- ✅ "Total Value" shows "(NET equity - matches Crypto.com)" label
- ✅ "Gross Assets" shows "(before borrowed)" label (only when gross ≠ net)
- ✅ "Borrowed" shown separately (never added to totals)

### 6. Verify Backend Contract
Check API response:
```bash
curl http://localhost:8000/api/dashboard/state | jq '.portfolio'
```

Expected structure:
```json
{
  "total_value_usd": 11814.17,    // NET equity (matches Crypto.com)
  "total_assets_usd": 12255.72,   // GROSS assets
  "total_borrowed_usd": 18813.09  // Borrowed (separate)
}
```

## Invariants (Must Always Hold)

1. **Backend Contract:**
   - `total_usd` (NET) must match Crypto.com Portfolio balance
   - All three values always returned: `total_usd`, `total_assets_usd`, `total_borrowed_usd`
   - Borrowed is NEVER added to either total

2. **Frontend Display:**
   - "Total Value" uses `total_value_usd` (NET equity)
   - "Gross Assets" uses `total_assets_usd` (informational only)
   - "Borrowed" uses `total_borrowed_usd` (shown separately)
   - Gross Assets never used in totals or calculations

3. **Data Source:**
   - All values come from Crypto.com API (single source of truth)
   - Pricing source: crypto_com_api (market_value or Crypto.com ticker prices)

## Regression Prevention

- ✅ Invariant comments in code
- ✅ Regression guard with PORTFOLIO_DEBUG
- ✅ Type safety (TypeScript interfaces)
- ✅ Clear UI labels ("NET equity - matches Crypto.com")

## Troubleshooting

If mismatch > $5:
1. Check PORTFOLIO_DEBUG logs for pricing source
2. Verify all assets have Crypto.com prices (not external sources)
3. Check if any assets are excluded (balance = 0 or no price)
4. Verify borrowed amounts are correctly calculated

