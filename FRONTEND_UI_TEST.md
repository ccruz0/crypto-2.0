# Frontend UI Test Checklist

## Prerequisites
- ✅ Backend is running on http://localhost:8000
- ✅ Backend tests passed (4/4)
- ⏳ Frontend should be running on http://localhost:3000

## UI Component Tests

### 1. Monitoring Tab - Active Alerts Section

#### Test 1.1: Refresh Button Visibility
- [ ] Navigate to Monitoring tab
- [ ] Locate "Active Alerts" section
- [ ] Verify "Refresh Signals" button appears in the header (right side)
- [ ] Button should have blue background (`bg-blue-600`)
- [ ] Button should show refresh icon (🔄) and text "Refresh Signals"

#### Test 1.2: Refresh Button Functionality
- [ ] Click "Refresh Signals" button
- [ ] Verify button shows spinner animation
- [ ] Verify button text changes to "Refreshing..."
- [ ] Verify button is disabled (grayed out, not clickable)
- [ ] Wait for refresh to complete (may take 10-30 seconds)
- [ ] Verify button returns to normal state
- [ ] Verify button is enabled again

#### Test 1.3: Visual Indicator During Refresh
- [ ] Click "Refresh Signals" button
- [ ] Verify "Recalculating signals..." message appears
- [ ] Verify spinner appears next to "Active Alerts" heading
- [ ] Verify indicator disappears when refresh completes
- [ ] Verify no errors in browser console

#### Test 1.4: Timestamp Display
- [ ] After clicking "Refresh Signals", wait for completion
- [ ] Verify timestamp appears below "Active Alerts" heading
- [ ] Format should be: "Signals calculated: [date] [time] [timezone]"
- [ ] Timestamp should be recent (within last minute)
- [ ] Timestamp should update after each refresh

### 2. Signal Consistency Tests

#### Test 2.1: Compare Monitoring vs Watchlist
- [ ] Note active alerts count in Monitoring tab
- [ ] Navigate to Watchlist tab
- [ ] Count symbols with:
  - `buy_alert_enabled = true` AND `signals.buy = true`
  - `sell_alert_enabled = true` AND `signals.sell = true`
- [ ] Return to Monitoring tab
- [ ] Verify active alerts count matches watchlist count

#### Test 2.2: Individual Symbol Verification
- [ ] In Watchlist, find a symbol with active BUY signal and `buy_alert_enabled = true`
- [ ] Note the symbol name
- [ ] Go to Monitoring tab
- [ ] Click "Refresh Signals"
- [ ] Verify the symbol appears in Active Alerts table with type "BUY"
- [ ] Repeat for SELL signals

#### Test 2.3: Alert Toggle Test
- [ ] In Watchlist, enable `buy_alert_enabled` for a symbol with active BUY signal
- [ ] Go to Monitoring tab
- [ ] Click "Refresh Signals"
- [ ] Verify symbol appears in Active Alerts
- [ ] Return to Watchlist, disable `buy_alert_enabled`
- [ ] Go to Monitoring tab
- [ ] Click "Refresh Signals"
- [ ] Verify symbol no longer appears in Active Alerts

### 3. Error Handling Tests

#### Test 3.1: Network Error Handling
- [ ] Stop backend server
- [ ] Click "Refresh Signals" button
- [ ] Verify error message appears
- [ ] Verify button returns to normal state
- [ ] Restart backend
- [ ] Click "Refresh Signals" again
- [ ] Verify it works correctly

#### Test 3.2: Timeout Handling
- [ ] Click "Refresh Signals" button
- [ ] Verify button shows loading state during long operations
- [ ] Verify UI remains responsive
- [ ] Verify no browser freezing

### 4. Browser Console Tests

#### Test 4.1: No Console Errors
- [ ] Open browser DevTools (F12)
- [ ] Go to Console tab
- [ ] Navigate to Monitoring tab
- [ ] Click "Refresh Signals"
- [ ] Verify no red errors in console
- [ ] Verify no warnings related to our changes

#### Test 4.2: Network Requests
- [ ] Open browser DevTools → Network tab
- [ ] Click "Refresh Signals"
- [ ] Verify request to `/api/monitoring/summary?force_refresh=true`
- [ ] Verify request returns 200 status
- [ ] Verify response includes `signals_last_calculated` field

## Expected UI Behavior

### Before Refresh
```
┌─────────────────────────────────────────┐
│ Active Alerts                    [🔄 Refresh Signals] │
│                                          │
│ [Alert table or "No active alerts"]      │
└─────────────────────────────────────────┘
```

### During Refresh
```
┌─────────────────────────────────────────┐
│ Active Alerts  [⏳ Recalculating signals...]  [⏳ Refreshing...] │
│                                          │
│ [Alert table or "No active alerts"]      │
└─────────────────────────────────────────┘
```

### After Refresh
```
┌─────────────────────────────────────────┐
│ Active Alerts                    [🔄 Refresh Signals] │
│ Signals calculated: 01/09/2026, 11:34:15 AM GMT+8 │
│                                          │
│ [Updated alert table]                   │
└─────────────────────────────────────────┘
```

## Test Results Template

### Test Execution
- **Date:** ___________
- **Browser:** ___________
- **Frontend URL:** ___________
- **Backend URL:** ___________

### Results
- [ ] Refresh Button Visibility: ✅ / ❌
- [ ] Refresh Button Functionality: ✅ / ❌
- [ ] Visual Indicator: ✅ / ❌
- [ ] Timestamp Display: ✅ / ❌
- [ ] Signal Consistency: ✅ / ❌
- [ ] Error Handling: ✅ / ❌
- [ ] Console Errors: ✅ / ❌

### Issues Found
1. ___________
2. ___________

## Quick Test Commands

### Check Backend
```bash
curl http://localhost:8000/api/monitoring/summary
```

### Check Frontend
```bash
curl http://localhost:3000
```

### Check API with Force Refresh
```bash
curl "http://localhost:8000/api/monitoring/summary?force_refresh=true"
```


