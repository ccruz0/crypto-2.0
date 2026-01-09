# Restart and Test Instructions

## Quick Start

### Option 1: Automated Script (Recommended)
```bash
cd /Users/carloscruz/automated-trading-platform
./restart_and_test.sh
```

When prompted, type `y` to start the backend.

### Option 2: Manual Steps

#### Step 1: Start Backend
```bash
cd backend

# Create virtual environment if needed
python3 -m venv venv
source venv/bin/activate

# Install dependencies if needed
pip install -r requirements.txt

# Start backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Step 2: Run Tests
In a new terminal:
```bash
cd backend
source venv/bin/activate
python3 test_monitoring_refresh.py
```

#### Step 3: Test Frontend
1. Start frontend (if not already running):
   ```bash
   cd frontend
   npm run dev
   ```

2. Open browser: http://localhost:3000
3. Navigate to **Monitoring** tab
4. Test the **"Refresh Signals"** button

## What to Test

### ✅ Backend API Tests

1. **Basic Endpoint**
   ```bash
   curl http://localhost:8000/api/monitoring/summary
   ```
   - Should return 200
   - Should include `signals_last_calculated` field

2. **Force Refresh**
   ```bash
   curl "http://localhost:8000/api/monitoring/summary?force_refresh=true"
   ```
   - Should return 200
   - Should include timestamp in `signals_last_calculated`
   - May take longer (30-60 seconds)

### ✅ Frontend UI Tests

1. **Refresh Button**
   - [ ] Button appears in Active Alerts section header
   - [ ] Button shows spinner when clicked
   - [ ] Button is disabled during refresh
   - [ ] "Recalculating signals..." message appears

2. **Timestamp Display**
   - [ ] Timestamp appears after refresh
   - [ ] Format: "Signals calculated: [date] [time] [timezone]"
   - [ ] Timestamp is recent (within last minute)

3. **Signal Consistency**
   - [ ] Active alerts in Monitoring match signals in Watchlist
   - [ ] Counts are consistent between both tabs

## Expected Results

### Successful Test Output
```
============================================================
MONITORING REFRESH FUNCTIONALITY TESTS
============================================================
Testing endpoint: http://localhost:8000/api/monitoring/summary

============================================================
TEST 1: Basic Monitoring Summary
============================================================
✅ Status Code: 200
✅ Active Alerts: 1
✅ Backend Health: healthy
✅ Signals Last Calculated: 2026-01-09T11:15:30.123456Z

============================================================
TEST 2: Force Refresh Signals
============================================================
✅ Force refresh returned timestamp
✅ Timestamp updated correctly

============================================================
TEST SUMMARY
============================================================
✅ PASS: Basic Summary
✅ PASS: Force Refresh
✅ PASS: Multiple Refreshes
✅ PASS: Response Structure

Total: 4/4 tests passed
🎉 All tests passed!
```

## Troubleshooting

### Backend Won't Start
- Check if port 8000 is in use: `lsof -i :8000`
- Check backend logs: `tail -f backend/backend.log`
- Verify Python version: `python3 --version` (should be 3.9+)

### Tests Fail with Connection Refused
- Ensure backend is running: `curl http://localhost:8000/api/health`
- Check backend is listening on correct port
- Verify no firewall blocking port 8000

### Timestamp Not Appearing
- Check backend logs for errors
- Verify watchlist has items with alerts enabled
- Check browser console for API errors

### Signals Don't Match
- Click "Refresh Signals" button
- Verify watchlist alert toggles are enabled
- Check backend logs for signal calculation details

## Files Changed

### Backend
- `backend/app/api/routes_monitoring.py` - Added force_refresh parameter and timestamp

### Frontend
- `frontend/src/lib/api.ts` - Updated API interface and function
- `frontend/src/app/components/MonitoringPanel.tsx` - Added UI components

### Test Files
- `backend/test_monitoring_refresh.py` - Automated test script
- `restart_and_test.sh` - Restart and test automation script

## Next Steps After Testing

1. ✅ Verify all tests pass
2. ✅ Test in browser UI
3. ✅ Verify signals match between Monitoring and Watchlist
4. ✅ Check for any console errors
5. ✅ Review backend logs for any warnings

## Success Criteria

- [x] Backend starts without errors
- [ ] All automated tests pass
- [ ] Refresh button works in UI
- [ ] Timestamp displays correctly
- [ ] Visual indicator appears during refresh
- [ ] Signals match between Monitoring and Watchlist
- [ ] No console errors
- [ ] No backend errors in logs

