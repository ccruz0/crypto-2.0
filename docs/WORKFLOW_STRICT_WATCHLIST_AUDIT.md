# Workflow: Strict Watchlist Audit

**Status:** ✅ Ready for Cursor Settings

This workflow performs a full strict audit of the Watchlist tab, ensuring complete alignment between backend logic, frontend display, and Business Rules.

---

## Workflow Configuration

### Name
```
Strict Watchlist Audit
```

### Trigger Keywords
```
audit watchlist
watchlist audit
strict audit
verify watchlist
check signals
```

### Auto-trigger
✅ **ENABLE** "Automatically run for matching messages"

---

## Workflow Prompt

Copy the following EXACT text into the Workflow Prompt field in Cursor Settings:

```
You act as an autonomous agent running a FULL STRICT AUDIT of the Watchlist tab for the automated-trading-platform.

Never ask the user questions.

Never wait for confirmation.

Run the full autonomous cycle:

INVESTIGATE → REASON → FIX → IMPLEMENT → TEST → DEPLOY → OPEN LIVE DASHBOARD → VALIDATE → ITERATE

Continue until EVERYTHING matches the Business Rules.

==================================================
CONTEXT
==================================================

Project:
automated-trading-platform

Remote host:
hilovivo-aws

Remote path:
 /home/ubuntu/automated-trading-platform

Business Rules:
- docs/monitoring/business_rules_canonical.md
- docs/monitoring/signal_flow_overview.md

Audit Workflow:
- docs/WORKFLOW_WATCHLIST_AUDIT.md

Autonomous Exec Rules:
- docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md

Constraints:
- You CAN generate alerts.
- You CANNOT create real trading orders.
- You MUST test backend + frontend + AWS + browser live.
- You MUST fix discrepancies until everything is correct.

==================================================
TASK
==================================================

Perform a STRICT audit of the Watchlist:

1. Compare backend BUY/SELL decision logic with Business Rules.
2. Compare backend strategy_state with frontend chips.
3. Verify RSI, MA, EMA, volume ratio, and all indicators match backend values precisely.
4. Verify Trading toggle and Alerts toggle persist and load correctly.
5. Verify alert generation works whenever:
   strategy.decision = BUY
   AND alert_enabled = true
   AND throttle allows.
6. Confirm alerts appear in:
   - Monitoring → Telegram Messages
   - Telegram (test channel)

==================================================
REQUIRED VALIDATIONS
==================================================

For EVERY symbol:

- If ALL buy_* flags are TRUE:
  → decision MUST be BUY
  → buy_signal MUST be true

- If decision=BUY AND alert_enabled=true:
  → an alert MUST be emitted.

Check explicitly:
- ALGO
- LDO
- TON

Frontend:
- Signals chip MUST equal backend decision.
- Index chip MUST equal backend index.
- RSI/MA/EMA/Volume displayed MUST match backend.

==================================================
HARD FAILURE CONDITION
==================================================

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

==================================================
AUTONOMOUS FIX LOOP
==================================================

For ANY mismatch:

1. Identify root cause.
2. Fix code.
3. Run tests.
4. Rebuild Docker images.
5. Deploy to AWS.
6. Open the Production Dashboard in a browser.
7. Validate visually (screenshots).
8. Repeat until NO mismatches remain.

==================================================
OUTPUT
==================================================

Create:
docs/WORKFLOW_WATCHLIST_STRICT_AUDIT_REPORT.md

Include:
- All mismatches found
- Fixes applied (with diffs)
- Validation evidence
- **Blocked Alert Regression section (if any patterns detected):**
  - List all offending messages
  - Root cause analysis
  - Fixes applied
- Final confirmation that Business Rules match perfectly
- **Explicit confirmation that NO blocked alert patterns were found**

START NOW.
```

---

## How to Create This Workflow in Cursor

1. Open Cursor Settings → Workflows
2. Click "Create New Workflow" or "+"
3. Set Name: `Strict Watchlist Audit`
4. Add Trigger Keywords (one per line):
   - `audit watchlist`
   - `watchlist audit`
   - `strict audit`
   - `verify watchlist`
   - `check signals`
5. Enable "Automatically run for matching messages"
6. Paste the Workflow Prompt (from above) into the prompt field
7. Save the workflow

---

## Usage

Once created, this workflow will automatically trigger when you type messages containing any of the trigger keywords, such as:
- "audit watchlist"
- "verify watchlist signals"
- "strict audit of watchlist"

The workflow will then autonomously:
- Investigate the Watchlist
- Compare backend vs frontend
- Fix any discrepancies
- Deploy and validate
- Generate a report

---

## Related Documents

- `docs/WORKFLOW_WATCHLIST_AUDIT.md` - Original Watchlist audit workflow
- `docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md` - Autonomous execution rules
- `docs/monitoring/business_rules_canonical.md` - Business rules reference

