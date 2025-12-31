# SL/TP Percentage Fix - Quick Start Guide

This guide will help you check, test, and deploy the SL/TP percentage fix.

## 🚀 Quick Start (3 Steps)

### Step 1: Check Current Settings

```bash
# Check DOT_USDT settings
python backend/scripts/check_update_dot_usdt_settings.py
```

**Output shows:**
- Current SL/TP percentages
- Current mode (aggressive/conservative)
- What will be used (watchlist vs defaults)

### Step 2: Update Settings (if needed)

```bash
# Option A: Update percentages only
python backend/scripts/check_update_dot_usdt_settings.py --update 5.0 5.0

# Option B: Update mode only
python backend/scripts/check_update_dot_usdt_settings.py --mode aggressive

# Option C: Update everything
python backend/scripts/check_update_dot_usdt_settings.py --all 5.0 5.0 aggressive
```

### Step 3: Test & Deploy

```bash
# Run tests
python backend/tests/test_sl_tp_percentage_fix.py

# Deploy (see DEPLOY_SL_TP_FIX.md for details)
git add backend/app/services/exchange_sync.py backend/app/services/sl_tp_checker.py
git commit -m "Fix: Use watchlist SL/TP percentages instead of defaults"
git push
```

## 📋 Detailed Commands

### Check Settings

```bash
# Basic check
python backend/scripts/check_update_dot_usdt_settings.py

# Example output:
# 📊 Current settings for DOT_USDT:
#    Mode: aggressive
#    SL Percentage: NULL (will use defaults)
#    TP Percentage: NULL (will use defaults)
# 
# 🎯 Effective percentages (what will be used):
#    SL: 2.0% (default for aggressive mode)
#    TP: 2.0% (default for aggressive mode)
```

### Update Settings

```bash
# Set to 5% SL and 5% TP
python backend/scripts/check_update_dot_usdt_settings.py --update 5.0 5.0

# Change mode to aggressive
python backend/scripts/check_update_dot_usdt_settings.py --mode aggressive

# Update everything at once
python backend/scripts/check_update_dot_usdt_settings.py --all 5.0 5.0 conservative
```

### Run Tests

```bash
# Option 1: Run with pytest (recommended)
pytest backend/tests/test_sl_tp_percentage_fix.py -v

# Option 2: Run directly
python backend/tests/test_sl_tp_percentage_fix.py
```

### Deploy to AWS

```bash
# SSH to server
ssh hilovivo-aws

# Navigate and pull
cd ~/automated-trading-platform
git pull

# Restart service
docker compose --profile aws restart backend-aws

# Monitor logs
docker compose --profile aws logs -f backend-aws | grep -E "(Reading SL/TP|Using watchlist|Using default)"
```

## 🔍 Verification

After deployment, verify the fix is working:

### 1. Check Logs

When next SL/TP order is created, look for:

```
✅ Good logs:
Reading SL/TP settings for DOT_USDT order XXXXX: watchlist_sl_pct=5.0, watchlist_tp_pct=5.0, mode=aggressive
Using watchlist SL percentage: 5.0% (from watchlist: 5.0%)
Using watchlist TP percentage: 5.0% (from watchlist: 5.0%)

❌ Bad logs (if still broken):
Using default SL percentage: 2.0% (watchlist had: 5.0)  # Should not happen!
```

### 2. Check Telegram Notification

Notification should show correct percentages in "Strategy Details":
```
📊 Strategy Details:
   📉 SL: 5.00%  ← Should match watchlist
   📈 TP: 5.00%  ← Should match watchlist
```

### 3. Verify Database

```sql
SELECT symbol, sl_percentage, tp_percentage, sl_tp_mode 
FROM watchlist_items 
WHERE symbol = 'DOT_USDT';
```

User settings should remain unchanged after order creation.

## 📚 Full Documentation

- **Check/Update Script**: `backend/scripts/check_update_dot_usdt_settings.py --help`
- **Deploy Guide**: See `DEPLOY_SL_TP_FIX.md`
- **Test Details**: See `backend/tests/test_sl_tp_percentage_fix.py`
- **Next Steps**: See `SL_TP_PERCENTAGE_FIX_NEXT_STEPS.md`

## ⚠️ Troubleshooting

### Script can't connect to database
```bash
# Check environment variables
echo $DATABASE_URL

# Or use .env file
source .env
python backend/scripts/check_update_dot_usdt_settings.py
```

### Tests failing
```bash
# Install pytest if needed
pip install pytest

# Run with verbose output
pytest backend/tests/test_sl_tp_percentage_fix.py -v -s
```

### Service won't restart
```bash
# Check logs for errors
docker compose --profile aws logs backend-aws --tail=100

# Force rebuild
docker compose --profile aws up -d --build --force-recreate backend-aws
```

## ✅ Success Checklist

- [ ] Checked current DOT_USDT settings
- [ ] Updated settings if needed
- [ ] Ran tests successfully
- [ ] Deployed to AWS
- [ ] Verified logs show correct percentages
- [ ] Confirmed Telegram notification shows correct values
- [ ] Verified user settings preserved in database

## 🎯 Expected Behavior

**Before Fix:**
- Always used 2% (aggressive default) or 3% (conservative default)
- Ignored watchlist custom percentages

**After Fix:**
- Uses watchlist percentages if set (and > 0)
- Falls back to defaults only if watchlist has None/0
- Preserves user settings in database
- Comprehensive logging shows what's being used



