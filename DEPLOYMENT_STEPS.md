# Watchlist Master Table - Deployment Steps

## ✅ Step 1: Database Migration - COMPLETED

The migration has been successfully run:
- ✅ Created `watchlist_master` table
- ✅ Migrated 23 rows from `watchlist_items`
- ✅ Enriched with MarketData

**Migration script:** `backend/scripts/run_watchlist_master_migration.py`

## Step 2: Test Endpoints Locally

### Start Backend Server

```bash
cd backend
# Activate virtual environment if you have one
source venv/bin/activate  # or your venv path

# Start server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Test Endpoints

Run the test script:

```bash
cd backend
python3 scripts/test_watchlist_master_endpoints.py
```

Or test manually:

```bash
# Test GET endpoint
curl http://localhost:8000/api/dashboard | jq '.[0] | {symbol, field_updated_at}'

# Test PUT endpoint
curl -X PUT http://localhost:8000/api/dashboard/symbol/BTC_USDT \
  -H "Content-Type: application/json" \
  -d '{"buy_alert_enabled": true}' | jq
```

### Expected Results

1. **GET /api/dashboard** should:
   - Return items from `watchlist_master` table
   - Include `field_updated_at` in each item
   - Show 23 items (or however many you have)

2. **PUT /api/dashboard/symbol/{symbol}** should:
   - Update the master table
   - Return updated item with `field_updated_at` showing the changed field
   - Include `updated_fields` array

## Step 3: Deploy Backend

### For AWS/Production

1. **Build and push Docker image** (if using Docker):
   ```bash
   cd backend
   docker build -t your-registry/watchlist-master:latest .
   docker push your-registry/watchlist-master:latest
   ```

2. **Or deploy directly** (if using direct deployment):
   ```bash
   # Copy updated files to server
   scp -r backend/app/models/watchlist_master.py user@server:/path/to/backend/app/models/
   scp -r backend/app/services/watchlist_master_seed.py user@server:/path/to/backend/app/services/
   scp backend/app/api/routes_dashboard.py user@server:/path/to/backend/app/api/
   scp backend/market_updater.py user@server:/path/to/backend/
   
   # Run migration on production database
   ssh user@server "cd /path/to/backend && python3 scripts/run_watchlist_master_migration.py"
   
   # Restart backend service
   ssh user@server "sudo systemctl restart your-backend-service"
   ```

3. **Verify deployment**:
   ```bash
   curl https://your-api-domain.com/api/dashboard | jq '.[0] | {symbol, field_updated_at}'
   ```

## Step 4: Deploy Frontend

### Build Frontend

```bash
cd frontend
npm install  # or yarn install
npm run build  # or yarn build
```

### Deploy

1. **Copy built files to server**:
   ```bash
   scp -r frontend/.next user@server:/path/to/frontend/
   scp -r frontend/src/components/WatchlistCell.tsx user@server:/path/to/frontend/src/components/
   scp -r frontend/src/styles/watchlist.css user@server:/path/to/frontend/src/styles/
   scp frontend/src/app/api.ts user@server:/path/to/frontend/src/app/
   ```

2. **Or if using a build service** (Vercel, Netlify, etc.):
   - Push to git repository
   - Build service will automatically deploy

3. **Restart frontend service** (if needed):
   ```bash
   ssh user@server "sudo systemctl restart your-frontend-service"
   ```

## Step 5: Monitor for Issues

### Check Logs

**Backend logs:**
```bash
# Check for errors
tail -f /var/log/your-backend/app.log | grep -i "watchlist_master\|error"

# Check for successful updates
tail -f /var/log/your-backend/app.log | grep "Updated watchlist_master"
```

**Frontend logs:**
- Check browser console for errors
- Check network tab for failed API calls

### Verify Functionality

1. **Check API responses**:
   ```bash
   curl https://your-api-domain.com/api/dashboard | jq '.[0]'
   ```
   - Should include `field_updated_at` field
   - Should have data from master table

2. **Test UI**:
   - Open watchlist page
   - Hover over cells - should show "Last updated" tooltip
   - Make an edit - should show "✓ Saved" feedback
   - Values updated in last 60 seconds should be highlighted

3. **Check data consistency**:
   - Make an edit in UI
   - Refresh page
   - Verify edit persisted
   - Verify UI shows same data as API response

### Common Issues

1. **Migration failed**:
   - Check database connection
   - Verify table doesn't already exist
   - Check column names match

2. **API returns empty**:
   - Check seeding service is running
   - Verify master table has data
   - Check logs for errors

3. **Frontend not showing timestamps**:
   - Verify API response includes `field_updated_at`
   - Check browser console for errors
   - Verify `WatchlistCell` component is being used

4. **Updates not persisting**:
   - Check backend logs for errors
   - Verify PUT endpoint is being called
   - Check database for actual updates

## Rollback Plan

If issues arise:

1. **Backend rollback**:
   ```bash
   # Revert routes_dashboard.py to old version
   git checkout HEAD~1 backend/app/api/routes_dashboard.py
   # Restart service
   ```

2. **Frontend rollback**:
   ```bash
   # Revert API calls to old endpoints
   git checkout HEAD~1 frontend/src/app/api.ts
   # Rebuild and redeploy
   ```

3. **Data safety**:
   - Old `watchlist_items` table is untouched
   - Master table can be dropped if needed: `DROP TABLE watchlist_master;`
   - Data can be re-seeded from `watchlist_items` anytime

## Success Criteria

✅ Migration completed successfully
✅ GET /api/dashboard returns data from master table
✅ PUT /api/dashboard/symbol/{symbol} updates master table
✅ Frontend shows tooltips with "Last updated"
✅ Frontend shows "Saved" feedback after edits
✅ Values updated in last 60 seconds are highlighted
✅ No discrepancies between UI and API

## Next Steps After Deployment

1. Monitor for 24-48 hours
2. Check for any performance issues
3. Verify all background jobs are writing to master table
4. Update any other services that modify watchlist data
5. Consider removing old `watchlist_items` table (after thorough testing)

