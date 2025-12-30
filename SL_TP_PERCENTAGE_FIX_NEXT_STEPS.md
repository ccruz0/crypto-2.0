# SL/TP Percentage Fix - Next Steps

## Summary
Fixed the issue where SL/TP orders were being created with 2% defaults instead of using custom watchlist percentages.

## Files Modified
1. `backend/app/services/exchange_sync.py` - Fixed percentage reading and persistence logic
2. `backend/app/services/sl_tp_checker.py` - Fixed percentage reading logic (2 occurrences)

## Immediate Actions

### 1. Verify Watchlist Settings in Database
Check if DOT_USDT has custom percentages set:

```sql
SELECT symbol, sl_percentage, tp_percentage, sl_tp_mode 
FROM watchlist_items 
WHERE symbol = 'DOT_USDT';
```

**Expected result:**
- If percentages are set (e.g., 5%, 3%, etc.) → The fix will use those values
- If percentages are NULL or 0 → The fix will use defaults (2% aggressive, 3% conservative)

### 2. Test the Fix Locally (Optional)
If you want to test before deploying:

```bash
# Start backend in development mode
cd backend
python -m uvicorn app.main:app --reload

# Monitor logs when next SL/TP order is created
# Look for these log messages:
# - "Reading SL/TP settings for {symbol}"
# - "Using watchlist SL percentage: X%" or "Using default SL percentage: X%"
# - "Using watchlist TP percentage: X%" or "Using default TP percentage: X%"
```

### 3. Deploy to AWS
The changes are ready to deploy. Options:

**Option A: Deploy via Git (if using CI/CD)**
```bash
git add backend/app/services/exchange_sync.py backend/app/services/sl_tp_checker.py
git commit -m "Fix: Use watchlist SL/TP percentages instead of defaults

- Added validation to check for None AND > 0 before using watchlist percentages
- Added comprehensive logging to track which percentages are used
- Fixed persistence logic to preserve user settings
- Applied fix to both exchange_sync.py and sl_tp_checker.py"
git push
```

**Option B: Manual Deploy**
```bash
# SSH to AWS server
ssh hilovivo-aws

# Navigate to project
cd ~/automated-trading-platform

# Pull latest changes
git pull

# Restart backend services
docker compose --profile aws restart backend-aws

# Or rebuild if needed
docker compose --profile aws up -d --build backend-aws
```

### 4. Monitor After Deployment

**Check logs for the fix working:**
```bash
# SSH to AWS
ssh hilovivo-aws

# Watch logs in real-time
docker compose --profile aws logs -f backend-aws | grep -E "(SL/TP|sl_percentage|tp_percentage|Reading SL/TP|Using watchlist|Using default)"

# When next SL/TP order is created, you should see:
# ✅ "Reading SL/TP settings for DOT_USDT: watchlist_sl_pct=X, watchlist_tp_pct=Y, mode=..."
# ✅ "Using watchlist SL percentage: X%" (if custom percentages set)
# ✅ OR "Using default SL percentage: 2.0%" (if no custom percentages)
```

**Check Telegram notifications:**
- Next time SL/TP orders are created, the notification should show the correct percentages
- Verify the "Strategy Details" section shows the expected values

### 5. Verify Database After First Order Creation

After the next SL/TP order is created, verify that user settings are preserved:

```sql
-- Check that custom percentages weren't overwritten
SELECT symbol, sl_percentage, tp_percentage, sl_tp_mode, sl_price, tp_price
FROM watchlist_items 
WHERE symbol = 'DOT_USDT';
```

**Expected behavior:**
- If user had custom percentages → They should remain unchanged
- If user had NULL percentages → They will be updated to show what defaults were used (for dashboard visibility)

### 6. Test Edge Cases (Optional but Recommended)

1. **Test with symbol that has custom percentages:**
   - Set `sl_percentage = 5.0` and `tp_percentage = 5.0` in watchlist
   - Create SL/TP orders
   - Verify orders use 5% not 2%

2. **Test with symbol that has NULL percentages:**
   - Ensure `sl_percentage = NULL` and `tp_percentage = NULL`
   - Verify defaults are used (2% aggressive or 3% conservative)

3. **Test with 0 values:**
   - Set percentages to 0
   - Verify defaults are used (0% is invalid)

## Success Criteria

✅ **Fix is working if:**
- Logs show "Using watchlist SL percentage: X%" when custom percentages are set
- Logs show "Using default SL percentage: X%" when no custom percentages
- Telegram notifications show correct percentages
- User's custom percentages are preserved in database
- Orders are created with correct prices based on watchlist percentages

## Rollback Plan (if needed)

If issues arise, you can revert:

```bash
git revert <commit-hash>
# Or manually revert the changes to the two files
```

## Questions to Answer

1. What are the expected SL/TP percentages for DOT_USDT?
   - Check database: `SELECT sl_percentage, tp_percentage FROM watchlist_items WHERE symbol = 'DOT_USDT';`

2. Should we update DOT_USDT's percentages to desired values?
   ```sql
   UPDATE watchlist_items 
   SET sl_percentage = 5.0, tp_percentage = 5.0 
   WHERE symbol = 'DOT_USDT';
   ```

3. Are there other symbols that might have the same issue?
   - Check: `SELECT symbol, sl_percentage, tp_percentage FROM watchlist_items WHERE sl_percentage IS NULL OR tp_percentage IS NULL;`

## Additional Notes

- The fix applies to both automatic SL/TP creation (via `exchange_sync`) and manual creation (via `sl_tp_checker`)
- Logging is comprehensive and will help diagnose any future issues
- The fix preserves backward compatibility - symbols without custom percentages will continue using defaults


