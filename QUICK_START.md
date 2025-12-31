# Quick Start - Watchlist Master Table

## 🚀 Quick Deployment (5 minutes)

### 1. Verify Migration (Already Done ✅)
```bash
cd backend
python3 scripts/verify_watchlist_master.py
```
**Result:** ✅ All verifications passed

### 2. Test Locally (Optional)

**Start server:**
```bash
cd backend
uvicorn app.main:app --reload
```

**Test endpoints:**
```bash
# In another terminal
cd backend
python3 scripts/test_watchlist_master_endpoints.py
```

### 3. Deploy to Production

**Backend:**
```bash
# Copy files
scp backend/app/models/watchlist_master.py user@server:/path/to/backend/app/models/
scp backend/app/services/watchlist_master_seed.py user@server:/path/to/backend/app/services/
scp backend/app/api/routes_dashboard.py user@server:/path/to/backend/app/api/
scp backend/market_updater.py user@server:/path/to/backend/
scp backend/app/services/portfolio_cache.py user@server:/path/to/backend/app/services/
scp backend/scripts/run_watchlist_master_migration.py user@server:/path/to/backend/scripts/

# Run migration
ssh user@server "cd /path/to/backend && python3 scripts/run_watchlist_master_migration.py"

# Restart service
ssh user@server "sudo systemctl restart your-backend-service"
```

**Frontend:**
```bash
# Copy files
scp frontend/src/components/WatchlistCell.tsx user@server:/path/to/frontend/src/components/
scp frontend/src/styles/watchlist.css user@server:/path/to/frontend/src/styles/
scp frontend/src/app/api.ts user@server:/path/to/frontend/src/app/

# Build and deploy (or push to git for auto-deploy)
```

### 4. Verify

```bash
# Check API
curl https://your-api-domain.com/api/dashboard | jq '.[0] | {symbol, field_updated_at}'

# Check UI
# - Open watchlist page
# - Hover over cells (should show tooltips)
# - Make an edit (should show "Saved")
# - Check recent updates are highlighted
```

## ✅ Done!

Your watchlist now uses the master table architecture with:
- Single source of truth
- Per-field timestamps
- Visual feedback
- Zero discrepancies












