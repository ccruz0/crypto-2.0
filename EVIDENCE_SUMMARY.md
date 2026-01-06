# Evidence Summary - Duplicate Signals Requests

## Status
✅ Backend duplicate guard enabled: `SIGNALS_DUP_GUARD=1` in docker-compose.yml
✅ Services restarted
✅ Evidence capture attempted

## Network Evidence (from Playwright)

**Signals Requests Captured:**
- ALGO_USDT: **3 requests**
- AAVE_USDT: 2 requests
- BTC_USDT: 2 requests
- DOT_USDT: 1 request
- ADA_USD: 1 request
- SUI_USDT: 1 request

**Screenshot:** `evidence_network.png`

## Browser Console Evidence

**Note:** Stack traces (`window.__SIGNALS_HTTP__`) are empty, which suggests:
- Frontend may be running in production mode (stack capture only works in dev)
- OR the code hasn't loaded yet when capture runs

**To capture manually in browser:**
1. Open http://localhost:3000
2. Open DevTools Console
3. Hard reload (Cmd+Shift+R)
4. Wait 10 seconds
5. Run: `window.__SIGNALS_HTTP__.filter(x => x.symbol === "ALGO_USDT")`
6. Run: `window.__PRINT_SIGNALS_STACKS__()`

## Backend Logs Evidence

**Command to check:**
```bash
docker compose --profile aws logs --tail=200 backend-aws | grep "\[signals\]"
```

**Expected output format:**
```
[signals] symbol=ALGO_USDT rid=sig_... ts=...
[signals] DUP_BLOCK symbol=ALGO_USDT rid=... (if duplicates detected)
```

## Next Steps

1. **Manual browser capture required:**
   - Open browser to http://localhost:3000
   - Follow steps in "Browser Console Evidence" section above
   - Paste output of `window.__SIGNALS_HTTP__.filter(x => x.symbol === "ALGO_USDT")`

2. **Backend logs:**
   - Run the grep command above
   - Count distinct `rid=` values for ALGO_USDT
   - Look for `DUP_BLOCK` entries

3. **Screenshots needed:**
   - Network tab filtered by "signals"
   - Console showing `[signals-http] START` and `STACK` lines
   - Backend logs showing `[signals]` entries

## Files Changed

1. `docker-compose.yml` - Added `SIGNALS_DUP_GUARD=1` to backend-aws environment
2. `frontend/src/app/api.ts` - Stack trace capture (dev only)
3. `backend/app/api/routes_signals.py` - Duplicate blocking with env flag


