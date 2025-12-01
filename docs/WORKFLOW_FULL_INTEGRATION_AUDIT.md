# ✅ Cursor Workflow AI – "Watchlist + Backend Full Integration Audit (Autonomous)"

**Workflow Name:** `Watchlist + Backend Full Integration Audit (Autonomous)`

**This is a Workflow AI Prompt for Cursor. Use this workflow for full system integration issues where frontend and backend must be validated together.**

---

## Workflow AI Prompt

This workflow enforces a fully autonomous FULL SYSTEM INTEGRATION audit and fix cycle for the automated-trading-platform.

This workflow combines Watchlist Audit + Backend Strategy Audit to ensure complete consistency between:
- Frontend UI state
- Backend decision logic
- Database state
- Alert emission
- Signal display

You MUST always work end-to-end, validating both frontend and backend together.

---

## GLOBAL RULES

- **NEVER ask the user questions.**
- **NEVER generate real orders on Crypto.com or any live exchange.**
- **ALWAYS validate frontend AND backend together.**
- **ALWAYS ensure UI state matches backend state.**
- **ALWAYS follow the canonical business rules.**
- **ALWAYS iterate until frontend and backend are perfectly aligned.**

---

## SCOPE OF THIS WORKFLOW

This workflow is executed when there are integration issues between frontend and backend. You MUST:

### 1. Understand the Request

- Parse the integration issue carefully.
- Identify which components are misaligned:
  - UI signals vs backend decisions
  - Buy index vs backend index
  - Toggle persistence (Trade, Alerts)
  - Parameter loading (RSI/MA/EMA/Volume)
  - Alert emission rules
  - Monitoring tab display

### 2. Execute Backend Audit First

**Run the Backend Strategy & Alerts Audit workflow:**
- Reference: `docs/WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md`
- Validate backend logic is correct
- Ensure backend follows canonical rules
- Fix any backend issues found
- Deploy backend fixes to AWS

### 3. Execute Watchlist Audit Second

**Run the Watchlist Audit workflow:**
- Reference: `docs/WORKFLOW_WATCHLIST_AUDIT.md`
- Validate frontend displays backend decisions correctly
- Ensure UI state matches backend state
- Fix any frontend issues found
- Deploy frontend fixes

### 4. Full Integration Validation

**Validate end-to-end consistency:**

- **UI Signals vs Backend Decisions:**
  - Open live dashboard: `https://monitoring-ai-dashboard-nu.vercel.app/`
  - Navigate to Watchlist tab
  - For each coin, compare:
    - Frontend signal chip (BUY/SELL/WAIT) vs backend `strategy.decision`
    - Frontend index percentage vs backend `strategy.index`
    - Frontend tooltip reasons vs backend `strategy.reasons`

- **Buy Index Consistency:**
  - Frontend INDEX label vs backend `strategy.index`
  - Verify calculation matches (percentage of buy_* flags that are True)

- **Toggle Persistence:**
  - Toggle "Trade" to YES/NO
  - Refresh page
  - Verify toggle state persists
  - Check backend DB: `trade_enabled` matches UI
  - Toggle "Alerts" to ON/OFF
  - Refresh page
  - Verify toggle state persists
  - Check backend DB: `alert_enabled` matches UI

- **Parameter Loading:**
  - Compare frontend displayed values with backend API:
    - RSI: Frontend vs `/api/watchlist` → `coin.rsi`
    - MA50: Frontend vs `/api/watchlist` → `coin.ma50`
    - EMA10: Frontend vs `/api/watchlist` → `coin.ema10`
    - MA200: Frontend vs `/api/watchlist` → `coin.ma200`
    - Volume Ratio: Frontend vs `/api/watchlist` → `coin.volume_ratio`
  - Values must match within expected rounding

- **Alert Emission Rules:**
  - Enable alerts for a test symbol (Trade=NO to avoid real orders)
  - Force conditions that should trigger BUY/SELL
  - Verify:
    - Alert appears in Monitoring → Telegram Messages
    - Backend logs show `DEBUG_STRATEGY_FINAL` with correct decision
    - Telegram send function is called
    - No real order is created (because Trade=NO)

- **Monitoring Tab Display:**
  - Check Monitoring → Telegram Messages
  - Verify alerts appear when conditions are met
  - Verify alerts respect throttle rules
  - Verify risk blocks orders, not alerts

### 5. Browser E2E Testing

**Run full browser validation:**

- **Open production dashboard:**
  ```
  https://monitoring-ai-dashboard-nu.vercel.app/
  ```

- **Navigate to Watchlist tab**

- **Take screenshots:**
  - Full Watchlist view
  - Signal chips for multiple coins
  - Index labels
  - Tooltips showing reasons
  - Toggle states

- **Check browser console:**
  - No JavaScript errors
  - No API call failures
  - No network errors

- **Check Network tab:**
  - API calls succeed (200 status)
  - Response data matches displayed UI
  - No 502/504 errors

- **Compare frontend and backend:**
  - For each coin, fetch backend data:
    ```bash
    curl -s "https://monitoring-ai-dashboard-nu.vercel.app/api/market/top-coins-data" | jq '.coins[0]'
    ```
  - Compare with UI display
  - Verify they match

### 6. Backend Logs Validation

**Check backend logs for consistency:**

- **SSH to AWS:**
  ```bash
  ssh hilovivo-aws
  cd /home/ubuntu/automated-trading-platform
  ```

- **Check SignalMonitor logs:**
  ```bash
  docker logs automated-trading-platform-backend-aws-1 --tail 500 | grep -E 'DEBUG_STRATEGY_FINAL|DEBUG_BUY_FLAGS|DEBUG_RESOLVED_PROFILE'
  ```

- **Verify:**
  - Strategy decisions match UI signals
  - Buy flags are calculated correctly
  - Profile resolution is correct
  - Alerts are emitted when conditions are met

- **Check Monitoring entries:**
  ```bash
  # Query monitoring table to verify alerts were recorded
  ```

### 7. Database State Validation

**Verify database state matches UI:**

- **Check watchlist items:**
  - `alert_enabled` matches UI toggle
  - `trade_enabled` matches UI toggle
  - `buy_alert_enabled` matches UI toggle
  - `sell_alert_enabled` matches UI toggle

- **Check canonical selector:**
  - Verify `get_canonical_watchlist_item` returns the correct row
  - Verify UI updates the same row that SignalMonitor reads

- **Check strategy state:**
  - Verify `strategy.decision` in API matches UI
  - Verify `strategy.index` in API matches UI
  - Verify `strategy.reasons` in API matches tooltip

### 8. Fix Integration Issues

**If mismatches are found:**

- **Frontend-Backend Mismatch:**
  - If UI shows wrong signal → Fix frontend to use backend `strategy.decision`
  - If UI shows wrong index → Fix frontend to use backend `strategy.index`
  - If UI shows wrong reasons → Fix frontend to use backend `strategy.reasons`

- **Toggle Persistence Issues:**
  - If toggles don't persist → Fix API endpoint to save correctly
  - If toggles don't match DB → Fix canonical selector usage
  - If SignalMonitor reads wrong row → Fix selector in SignalMonitor

- **Parameter Loading Issues:**
  - If RSI/MA/EMA don't match → Fix backend calculation or frontend display
  - If volume ratio doesn't match → Fix backend calculation or frontend display

- **Alert Emission Issues:**
  - If alerts don't fire → Fix SignalMonitor logic
  - If alerts fire incorrectly → Fix business rule implementation

### 9. Deploy Both Sides

- **Deploy backend fixes:**
  ```bash
  ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws up --build -d backend-aws'
  ```

- **Deploy frontend fixes:**
  - Push to git (triggers Vercel deployment)
  - Or manually deploy to Vercel

- **Wait for deployment:**
  - Backend: Wait for container to be healthy
  - Frontend: Wait for Vercel build to complete

### 10. Re-validate Integration

**After deployment, re-run full validation:**

- Open live dashboard
- Navigate to Watchlist
- Compare UI with backend API
- Check browser console
- Check backend logs
- Verify toggles persist
- Verify alerts work correctly

**If issues remain:**
- Fix the root cause
- Redeploy
- Re-validate
- Repeat until perfect

### 11. Final Report

- What integration issues were found?
- Which components were misaligned?
- What fixes were applied (frontend and backend)?
- Validation results:
  - UI signals match backend decisions
  - Index matches backend calculation
  - Toggles persist correctly
  - Parameters match between UI and API
  - Alerts emit correctly
  - No real orders were created
  - Screenshots of final state

---

## Quick Reference Commands

### Backend API Check
```bash
curl -s "https://monitoring-ai-dashboard-nu.vercel.app/api/market/top-coins-data" | jq '.coins[0] | {symbol: .instrument_name, decision: .strategy_state.decision, index: .strategy_state.index}'
```

### Backend Logs
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker logs automated-trading-platform-backend-aws-1 --tail 500 | grep DEBUG_STRATEGY_FINAL'
```

### Frontend Validation
- Open: `https://monitoring-ai-dashboard-nu.vercel.app/`
- Navigate to Watchlist
- Check browser console
- Check Network tab

---

## Validation Checklist

- [ ] UI signals match backend `strategy.decision`
- [ ] UI index matches backend `strategy.index`
- [ ] UI tooltip reasons match backend `strategy.reasons`
- [ ] RSI/MA/EMA values match between UI and API
- [ ] Volume ratio matches between UI and API
- [ ] Trade toggle persists after refresh
- [ ] Alerts toggle persists after refresh
- [ ] Toggle state matches database
- [ ] SignalMonitor reads correct watchlist row
- [ ] Alerts emit when conditions are met
- [ ] Alerts respect throttle rules
- [ ] Risk blocks orders, not alerts
- [ ] No real orders were created
- [ ] Browser console has no errors
- [ ] Backend logs show correct decisions

---

## Notes

- This workflow combines both frontend and backend audits
- Always validate both sides together
- Ensure canonical selector is used consistently
- Never create real orders during testing
- Always validate in the live environment

