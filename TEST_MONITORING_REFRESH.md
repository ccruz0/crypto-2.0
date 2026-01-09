# Monitoring Refresh Functionality - Test Plan

## Overview
This document outlines the test plan for the new monitoring refresh functionality that includes:
1. Force refresh button to recalculate signals
2. Timestamp showing when signals were last calculated
3. Visual indicator when signals are being recalculated

## Changes Made

### Backend (`routes_monitoring.py`)
- ✅ Added `force_refresh` query parameter to `/monitoring/summary` endpoint
- ✅ Added `signals_last_calculated` timestamp to response
- ✅ Updated signal calculation logic to always recalculate for active watchlist items

### Frontend (`MonitoringPanel.tsx` & `api.ts`)
- ✅ Added refresh button in Active Alerts section
- ✅ Added visual indicator (spinner) during recalculation
- ✅ Added timestamp display showing when signals were last calculated
- ✅ Updated API call to support `forceRefresh` parameter

## Test Checklist

### 1. Backend API Tests

#### Test 1.1: Basic Endpoint
```bash
curl http://localhost:8000/api/monitoring/summary
```
**Expected:**
- Status 200
- Response includes `signals_last_calculated` field (may be null)
- Response includes all existing fields

#### Test 1.2: Force Refresh Parameter
```bash
curl "http://localhost:8000/api/monitoring/summary?force_refresh=true"
```
**Expected:**
- Status 200
- `signals_last_calculated` contains ISO timestamp
- Signals are recalculated (may take longer)
- Response includes updated alert counts

#### Test 1.3: Multiple Force Refreshes
```bash
# Run 3 times in sequence
curl "http://localhost:8000/api/monitoring/summary?force_refresh=true"
sleep 2
curl "http://localhost:8000/api/monitoring/summary?force_refresh=true"
sleep 2
curl "http://localhost:8000/api/monitoring/summary?force_refresh=true"
```
**Expected:**
- Each request returns a timestamp
- Timestamps are recent (within last minute)
- Alert counts are consistent (unless signals actually changed)

### 2. Frontend UI Tests

#### Test 2.1: Refresh Button Visibility
- [ ] Navigate to Monitoring tab
- [ ] Verify "Refresh Signals" button appears in Active Alerts section header
- [ ] Button should be on the right side of the header

#### Test 2.2: Refresh Button Functionality
- [ ] Click "Refresh Signals" button
- [ ] Verify spinner appears with "Refreshing..." text
- [ ] Verify button is disabled during refresh
- [ ] Wait for refresh to complete
- [ ] Verify spinner disappears
- [ ] Verify button is enabled again

#### Test 2.3: Timestamp Display
- [ ] After refresh, verify timestamp appears below "Active Alerts" heading
- [ ] Format: "Signals calculated: [date] [time] [timezone]"
- [ ] Timestamp should be recent (within last minute after refresh)

#### Test 2.4: Visual Indicator
- [ ] Click "Refresh Signals" button
- [ ] Verify "Recalculating signals..." message appears with spinner
- [ ] Verify indicator disappears when refresh completes

#### Test 2.5: Signal Consistency
- [ ] Note active alerts count in Monitoring tab
- [ ] Navigate to Watchlist tab
- [ ] Count symbols with active BUY/SELL signals (where alerts are enabled)
- [ ] Verify counts match between Monitoring and Watchlist

### 3. Integration Tests

#### Test 3.1: Signal Recalculation
- [ ] Enable buy_alert_enabled for a symbol in Watchlist
- [ ] Ensure symbol has active BUY signal
- [ ] Go to Monitoring tab
- [ ] Click "Refresh Signals"
- [ ] Verify symbol appears in Active Alerts with BUY type

#### Test 3.2: Multiple Symbols
- [ ] Enable alerts for multiple symbols
- [ ] Click "Refresh Signals"
- [ ] Verify all active signals appear in Active Alerts table
- [ ] Verify timestamp is updated

#### Test 3.3: No Active Signals
- [ ] Disable all alerts in Watchlist
- [ ] Click "Refresh Signals"
- [ ] Verify "No active alerts" message appears
- [ ] Verify timestamp is still updated

## Automated Test Script

A test script has been created at:
```
backend/test_monitoring_refresh.py
```

To run the automated tests:
```bash
cd backend
python3 test_monitoring_refresh.py
```

**Note:** The backend must be running for tests to pass.

## Manual Testing Steps

### Step 1: Start Backend
```bash
cd backend
# Option 1: Using docker-compose
docker-compose up backend

# Option 2: Direct uvicorn
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 2: Start Frontend
```bash
cd frontend
npm run dev
```

### Step 3: Test in Browser
1. Open http://localhost:3000 (or your frontend URL)
2. Navigate to Monitoring tab
3. Test the refresh button and verify all features

## Expected Behavior

### Normal Operation
- Monitoring tab loads with existing alerts
- Timestamp shows when signals were last calculated (if available)
- Refresh button is enabled

### During Refresh
- Button shows spinner and "Refreshing..." text
- Button is disabled
- "Recalculating signals..." indicator appears
- Page remains responsive

### After Refresh
- Spinner disappears
- Button returns to normal state
- Timestamp is updated with current time
- Active alerts table is updated with latest signals
- Signals match Watchlist view

## Troubleshooting

### Backend Not Responding
- Check if backend is running: `ps aux | grep uvicorn`
- Check backend logs for errors
- Verify port 8000 is not in use: `lsof -i :8000`

### Timestamp Not Appearing
- Check backend logs for signal calculation errors
- Verify watchlist items have alerts enabled
- Check browser console for API errors

### Signals Don't Match Watchlist
- Click "Refresh Signals" to force recalculation
- Verify watchlist items have correct alert toggles enabled
- Check backend logs for signal calculation details

## Success Criteria

✅ All automated tests pass
✅ Refresh button works correctly
✅ Timestamp displays correctly
✅ Visual indicator appears during refresh
✅ Signals match between Monitoring and Watchlist
✅ No console errors in browser
✅ No errors in backend logs

