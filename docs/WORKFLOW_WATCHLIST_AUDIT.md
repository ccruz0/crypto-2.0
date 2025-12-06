# ✅ Cursor Workflow AI – "Full Watchlist Audit (No Real Orders)"

**This is a Workflow AI Prompt for Cursor. Use this workflow after any backend/frontend change and deploy.**

---

## Mission

You are an autonomous engineer working on the project automated-trading-platform.

Your mission in this workflow is:

After any backend/frontend change and deploy, run a full, automated, end-to-end audit of the Watchlist tab, validating that:

- All business rules are correctly applied
- Alerts are emitted when criteria are met
- No real orders are ever created

You must work fully autonomously: do not ask the user questions, do not request prompts from the user, and do not stop after the first attempt if something is still wrong. You must iterate and fix issues until the Watchlist behaves correctly according to the business rules.

**Reference:** `docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md` for full execution protocol.

---

## 0. Environment & Paths

Assume:

- **Local project path:**
  ```bash
  cd /Users/carloscruz/automated-trading-platform
  ```

- **Remote host:**
  `hilovivo-aws` (configured in `~/.ssh/config`)

- **Remote project path:**
  `/home/ubuntu/automated-trading-platform`

- **All remote commands MUST be run like this:**
  ```bash
  sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && <COMMAND>'"
  ```

Never change SSH keys or credentials.

---

## 1. Hard rule: No real orders

During this workflow:

- **Never create real orders on the exchange.**
- **Only:**
  - Trigger signals/alerts
  - Use test orders, dry-run modes, or Trade = NO rows
- **If there is any code path that would call the real exchange API (Crypto.com) for BUY/SELL:**
  - Make sure it is disabled in this workflow (e.g. via env flags like `DRY_RUN=1` or `CREATE_REAL_ORDERS=false`, or by keeping `trade_enabled = False` in the DB for the symbols you use to test).

Your goal is to validate alerts and logic, not to place real trades.

---

## 2. Local validation before touching AWS

For any change you make:

1. **Go to the project root:**
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   ```

2. **Run backend tests:**
   ```bash
   cd backend
   pytest -q
   ```

3. **Run frontend lint + build:**
   ```bash
   cd ../frontend
   npm run lint
   npm run build
   ```

4. **If there are failures:**
   - Fix the code
   - Re-run tests/build
   - Do not proceed until both tests and build pass

---

## 3. Deploy to AWS

Once local tests and build pass:

1. **Deploy the stack to AWS:**
   ```bash
   sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose pull || true'"
   sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose up --build -d'"
   ```

2. **Wait for services to become healthy:**
   ```bash
   sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose ps'"
   ```

3. **Check backend logs for startup errors:**
   ```bash
   cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh --tail 200
   ```

If anything fails to start, you must:

- Inspect the error
- Fix it in code
- Rebuild and redeploy
- Only then continue with the audit.

---

## 4. Open the real Watchlist in the browser

Use Playwright or Cursor's built-in browser control to:

1. **Open the production dashboard URL:**
   ```
   https://dashboard.hilovivo.com/
   ```

2. **Navigate to the Watchlist tab.**

3. **Make sure the Dashboard loads without JS errors (check DevTools console).**

If there are console errors, you must:

- Inspect them
- Fix the code
- Redeploy
- Re-open the dashboard and re-check.

**Take at least one screenshot of the Watchlist tab in this workflow.**

---

## 5. Business Rules to validate on Watchlist

For each coin in the Watchlist that has Alerts ON:

You must verify the following, both visually in the frontend and via backend logs/API responses:

### 5.1. Strategy decision & Signals chip

- The Signals chip must be driven by the backend strategy decision:
  - `decision = BUY` → green BUY badge
  - `decision = SELL` → red SELL badge
  - `decision = WAIT` → neutral/grey WAIT badge
- The chip must not override the backend logic on the client side.
- Use the `/api/market/watchlist` or equivalent endpoint to fetch the JSON and confirm:
  - `strategy.decision`
  - `strategy.reasons`
  - `strategy.index` (if applicable)

If the UI state doesn't match backend decisions, fix the frontend so it uses backend values as the single source of truth.

### 5.2. Indicators consistency (RSI, MA, EMA, Volume)

For several test symbols (e.g. ALGO, LDO, TON, BTC):

- Confirm frontend displays:
  - RSI
  - MA50 / MA200 / EMA10
  - Volume ratio
  - Buy target
- Cross-check those values against:
  - The backend API response
  - Or the underlying DB if there is a debug script

They must match within expected rounding.

If there is any mismatch, fix either:
- The backend computation, or
- The frontend display/rounding

and redeploy, then re-check.

### 5.3. Canonical BUY rule

You must validate that when all BUY conditions are met, the system:

- Sets `strategy.decision = "BUY"`
- Sets `buy_signal = true`
- Turns the Signals chip to BUY (green)
- Emits a BUY alert to:
  - Monitoring → Telegram Messages
  - The configured Telegram channel (but without placing real orders)

You may temporarily adjust thresholds on a test symbol to force a BUY (e.g. lower RSI threshold) as long as you keep Trade = NO for that symbol to avoid real orders.

**Reference:** `docs/monitoring/business_rules_canonical.md` for canonical BUY conditions.

### 5.4. Alerts ON & Trading toggle

For any symbol:

- **When Alerts ON is enabled:**
  - The symbol must always be evaluated by the monitor
  - If criteria are met, a signal must be generated and an alert must be sent (subject only to throttle rules)
- **When Trading is set to YES/NO:**
  - This must be persisted in the backend (DB) correctly
  - You must confirm via:
    - The dashboard (toggle still correct after refresh)
    - The backend logs / debug script (e.g. `trade_enabled = True/False` for the canonical row)

**Trade=NO must not block alerts. It must only block real order creation.**

If toggles don't persist or the monitor uses a different row than the one the UI updates, you must correct the API / canonical selector behavior.

---

## 6. Alerts audit (without real orders)

For several test symbols with Alerts ON = true and Trade = NO:

1. **Force or wait for conditions that should produce:**
   - BUY signal
   - SELL signal

2. **Confirm:**
   - Monitoring → Telegram Messages shows the alert
   - Backend logs show:
     - `DEBUG_STRATEGY_FINAL` with `decision=BUY` or `decision=SELL`
     - The Telegram send function is called
   - There is no attempt to create a real order (no calls to the real exchange API) because Trade=NO or DRY_RUN is enabled.

If alerts do not fire when conditions are clearly met, you must:

- Inspect the strategy logic
- Fix the business rule implementation
- Redeploy and re-run this audit until it passes.

---

## 7. Throttle and risk rules

You must also verify:

- **Throttle:**
  - The system does not spam alerts when price/conditions haven't changed enough
  - Throttle applies to alerts, but only under the configured rules
- **Portfolio risk:**
  - Risk may block order creation
  - Risk must not block alerts
  - Any "blocked by risk" messages must clearly refer to orders, not alerts

Check logs to confirm:

- Alerts are sent
- If risk is triggered, it appears only in order diagnostics, not as "alert blocked".

## 7b. HARD FAILURE CONDITION: Blocked Alert Regression

⚠️ **CRITICAL:** If ANY of the following patterns are found in Monitoring entries or backend logs, the audit MUST immediately FAIL:

- 'send_buy_signal verification'
- 'send_sell_signal verification'
- 'Alerta bloqueada por send_buy_signal verification'
- 'Alerta bloqueada por send_sell_signal verification'
- 'BLOQUEADO' (or 'BLOCKED') together with 'send_buy_signal'
- 'BLOQUEADO' (or 'BLOCKED') together with 'send_sell_signal'

**Rule:** Portfolio / business rules may block ORDERS, but must NEVER block ALERTS.

**Action on detection:**
1. Mark the audit as FAILED
2. Stop claiming success
3. Add a section "Blocked Alert Regression Detected" to the report
4. List all offending messages found
5. Start a fix loop to remove this behavior from the codebase
6. Check telegram_notifier.py and signal_monitor.py logic

**How to check:**
- Search backend logs for the patterns above
- Check Monitoring → Telegram Messages for blocked messages
- Use grep: `grep -E "(send_buy_signal verification|send_sell_signal verification|BLOQUEADO.*send_buy|BLOQUEADO.*send_sell)"`

---

## 8. Automatic remediation & re-check

If, at any point in this audit, you find behavior that does not match the business rules, you must:

1. Locate the root cause in the code (backend or frontend)
2. Implement a clean, non-hacky fix
3. Re-run:
   - Local tests (`pytest`, `npm run lint`, `npm run build`)
   - AWS deploy (`docker compose up --build -d`)
   - Live Watchlist audit in the browser

Repeat this loop until:

- The Watchlist tab behavior fully matches the business rules
- Alerts are reliable and consistent
- UI and backend are fully aligned
- No real orders are created in this workflow

**Do not stop after the first attempt if something is still wrong.**

---

## 9. Reporting (for the user, at the end)

At the end of the workflow, produce a short, structured summary:

- What was checked (Watchlist, alerts, toggles, indicators, etc.)
- What issues were found
- What code changes were made
- **Blocked Alert Regression section (if any patterns detected):**
  - List all offending messages
  - Root cause analysis
  - Fixes applied
- Evidence of success:
  - Example logs
  - Description of alerts observed
  - Notes on UI behavior after the fix
- **Explicit confirmation that NO blocked alert patterns were found**

The final result the user expects is:

> "The Watchlist tab is fully audited, consistent with the business rules, alerts fire when they should, toggles persist correctly, and no real orders were placed during the process."

---

## Summary

If you follow this workflow for every Watchlist-related task, each change will be:

- Implemented
- Deployed
- Validated in the browser
- Iteratively fixed until it genuinely works end-to-end

**This workflow enforces the autonomous execution protocol defined in `docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md`.**

---

## Quick Reference Commands

### Local Testing
```bash
cd /Users/carloscruz/automated-trading-platform/backend && pytest -q
cd /Users/carloscruz/automated-trading-platform/frontend && npm run lint && npm run build
```

### AWS Deployment
```bash
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose down'"
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose up --build -d'"
```

### Health Check
```bash
curl -s https://dashboard.hilovivo.com/api/health
```

### Backend Logs
```bash
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker logs automated-trading-platform-backend-aws-1 --tail 200'"
```

### Dashboard URL
```
https://dashboard.hilovivo.com/
```

