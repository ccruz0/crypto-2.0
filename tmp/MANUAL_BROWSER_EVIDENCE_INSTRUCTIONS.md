# Manual Browser Evidence Capture Instructions

## Prerequisites

1. Frontend running: `cd frontend && npm run dev`
2. Backend running and reachable at http://localhost:8002
3. Chrome browser with DevTools

## Steps

### 1. Open Dashboard
- Navigate to: http://localhost:3000
- Open DevTools (F12 or Cmd+Option+I)

### 2. Configure Network Tab
- Go to **Network** tab
- Filter: Type `signals` in the filter box
- Enable **"Preserve log"** checkbox
- Clear existing requests (trash icon)

### 3. Configure Console Tab
- Go to **Console** tab
- Clear console (trash icon or Cmd+K)

### 4. Hard Reload
- **Hard reload:** Cmd+Shift+R (Mac) or Ctrl+Shift+R (Windows/Linux)
- This clears cache and forces fresh load

### 5. Wait 12 Seconds
- Do NOT interact with the page
- Wait exactly 12 seconds
- Watch for `[signals-http]` logs in console

### 6. Capture Network Tab
- In Network tab (filtered by "signals")
- Scroll to see all requests
- Take screenshot: **Cmd+Shift+4** (Mac) or use browser screenshot tool
- Save as: `tmp/evidence_network_signals.png`

### 7. Capture Console Logs
- In Console tab
- Scroll to see all `[signals-http]` logs
- Take screenshot
- Save as: `tmp/evidence_console_signals.png`

### 8. Run Console Commands

In the Console tab, run these commands one by one:

```javascript
// 1. Show signal counts
window.__SIG_COUNT__
```

```javascript
// 2. Show top 20 symbols by count
Object.entries(window.__SIG_COUNT__||{}).sort((a,b)=>b[1]-a[1]).slice(0,20)
```

Take a screenshot of the console output and save as: `tmp/evidence_console_counts.png`

### 9. Export Signal Counts

In Console, run:
```javascript
copy(JSON.stringify(window.__SIG_COUNT__||{}, null, 2))
```

This copies the JSON to clipboard. Paste it into a file:
- Create file: `tmp/sig_count.json`
- Paste the JSON content
- Save

## Expected Results

### Network Tab
- Should show 1 request per symbol (ALGO_USDT, AAVE_USDT, BTC_USDT, etc.)
- No duplicate requests for the same symbol
- All requests should complete (status 200)

### Console Tab
- Should show `[signals-http]` logs for each request
- Format: `[signals-http] symbol=ALGO_USDT t=... caller=... count=1 rid=...`
- No `⚠️ DUPLICATE DETECTED` warnings
- Each symbol should show `count=1` (not count=2 or higher)

### Signal Counts
- `window.__SIG_COUNT__` should show each symbol with count=1
- Example:
  ```json
  {
    "ALGO_USDT": 1,
    "AAVE_USDT": 1,
    "BTC_USDT": 1
  }
  ```

## Troubleshooting

### If you see duplicates:
1. Check the stack traces in console logs
2. Look for `⚠️ DUPLICATE DETECTED` warnings
3. Note which symbols have count > 1
4. Check the timestamps - duplicates should be within 5 seconds

### If no requests appear:
1. Check backend is running: `curl http://localhost:8002/api/health`
2. Check frontend is in dev mode (not production build)
3. Hard reload again (Cmd+Shift+R)
4. Wait longer (up to 20 seconds)

### If counts are missing:
1. Check console for errors
2. Verify `window.__SIG_COUNT__` exists: `typeof window.__SIG_COUNT__`
3. Check if instrumentation is active (should see `[signals-http]` logs)

## Files to Create

After following these steps, you should have:
- ✅ `tmp/evidence_network_signals.png`
- ✅ `tmp/evidence_console_signals.png`
- ✅ `tmp/evidence_console_counts.png`
- ✅ `tmp/sig_count.json`

## Verification

After capturing evidence, verify:
- ✅ No symbol has count > 1 in first 12 seconds
- ✅ Network tab shows 1 request per symbol
- ✅ Console shows no duplicate warnings
- ✅ All requests complete successfully

If all checks pass: **✅ FIX VERIFIED**



