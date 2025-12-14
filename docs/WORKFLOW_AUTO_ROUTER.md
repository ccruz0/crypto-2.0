# ✅ Cursor Workflow Auto-Router

**This document defines the automatic workflow selection system for all user requests.**

**CRITICAL:** You must ALWAYS classify the user's request into one of the predefined categories and automatically execute the correct Workflow from Cursor Settings.

**NEVER ask which workflow to use.**
**NEVER wait for clarification.**
**NEVER execute code or patches outside of the correct workflow context.**
**ALWAYS start the corresponding workflow immediately.**

---

## WORKFLOW AUTO-SELECTION RULES

When the user sends ANY task, first classify the task using the rules below.

### 1. FRONTEND UI / WATCHLIST UI / SIGNAL CHIP ISSUES

**Examples:**
- "The button doesn't update"
- "The green chip should appear but doesn't"
- "The MA/RSI values are not displayed correctly"
- "The Watchlist tabs don't load"
- "UI mismatch between what backend returns and what we see"
- "Signals chip shows wrong color"
- "Index percentage is incorrect"
- "Tooltip shows wrong information"
- "Presets dropdown not working"
- "Toggle buttons not responding"

**→ RUN WORKFLOW:** **Watchlist Audit (Autonomous)**
- Reference: `docs/WORKFLOW_WATCHLIST_AUDIT.md`

---

### 2. BACKEND STRATEGY / ALERT LOGIC / SIGNAL MONITOR

**Examples:**
- "A BUY should be triggered but isn't"
- "Volume/MA/RSI logic is wrong"
- "Alerts are not being sent or sent twice"
- "Risk is blocking alerts incorrectly"
- "Backend and UI disagree"
- "SignalMonitor or BuyIndexMonitor behaving incorrectly"
- "Canonical BUY rule not working"
- "Throttling not working correctly"
- "Strategy decision doesn't match flags"
- "Telegram alerts not sending"
- "Monitoring tab shows wrong status"

**→ RUN WORKFLOW:** **Backend Strategy & Alerts Audit (Autonomous)**
- Reference: `docs/WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md`

---

### 3. DEVOPS / AWS / DEPLOYMENT / DOCKER

**Examples:**
- "Backend is not deploying"
- "Docker container isn't starting"
- "Vercel 404 / Next.js issues"
- "AWS service not running"
- "Container health check failing"
- "Build errors in deployment"
- "Environment variables not set"
- "SSH connection issues"
- "Docker compose errors"

**→ RUN WORKFLOW:** **DevOps Deployment Fix (Autonomous)**
- Reference: `docs/WORKFLOW_DEVOPS_DEPLOYMENT.md` (to be created if needed)

---

### 4. FULL SYSTEM INTEGRATION ISSUES

**Examples:**
- "Frontend and backend mismatch"
- "DB state doesn't match UI"
- "Alerts appear but signals are wrong"
- "Watchlist toggles don't persist"
- "Backend logs don't match watchlist behavior"
- "UI shows one thing, backend shows another"
- "Toggles don't save correctly"
- "Canonical selector returning wrong row"

**→ RUN THIS COMBINED WORKFLOW:**
**Watchlist + Backend Full Integration Audit (Autonomous)**
- Execute both workflows in sequence:
  1. First: `docs/WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md`
  2. Then: `docs/WORKFLOW_WATCHLIST_AUDIT.md`
- Or create combined workflow if needed

---

### 5. TESTING / QA / END-TO-END CHECKS

**Examples:**
- "Audit everything after a deployment"
- "Check that alerts, UI, and backend logic are aligned"
- "Simulate signals and ensure alerts are emitted"
- "Run full system validation"
- "Verify business rules compliance"
- "Check all toggles and alerts"

**→ RUN WORKFLOW:** **Watchlist Audit (Autonomous)**
- Reference: `docs/WORKFLOW_WATCHLIST_AUDIT.md`
- This workflow includes full end-to-end validation

---

### 6. FRONTEND CODE CHANGES / NEW FEATURES

**Examples:**
- "Add a new button to the Watchlist"
- "Change the color scheme"
- "Update the tooltip format"
- "Add a new column to the table"
- "Modify preset configuration UI"
- "Update React components"

**→ RUN WORKFLOW:** **Frontend Change (Validated e2e)**
- Reference: `docs/WORKFLOW_FRONTEND_CHANGE_VALIDATED.md`

---

## AFTER CLASSIFYING

Once the task is classified:

1. **IMMEDIATELY activate the correct Workflow from Cursor Settings.**
2. **NEVER ask follow-up questions.**
3. **NEVER produce patches until the workflow context is activated.**
4. **The workflow itself will produce the solution AND validate it end-to-end.**

---

## SAFETY RULES

- **NEVER execute real buy/sell orders.**
- **ALWAYS follow the business rules defined in:**
  - `docs/monitoring/business_rules_canonical.md`
  - `docs/monitoring/signal_flow_overview.md`
  - `docs/monitoring/audit_refactor_summary.md`
  - `docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md`
- **When UI depends on backend decision → trust backend only.**
- **When backend depends on watchlist state → read canonical row only.**

---

## WORKFLOW REFERENCE MAP

| Workflow Name | Document | Use Case |
|--------------|----------|----------|
| **Watchlist Audit (Autonomous)** | `docs/WORKFLOW_WATCHLIST_AUDIT.md` | UI issues, Watchlist validation, E2E testing |
| **Backend Strategy & Alerts Audit (Autonomous)** | `docs/WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md` | Backend logic, alerts, signals, strategy |
| **Frontend Change (Validated e2e)** | `docs/WORKFLOW_FRONTEND_CHANGE_VALIDATED.md` | Frontend code changes, new UI features |
| **DevOps Deployment Fix (Autonomous)** | `docs/WORKFLOW_DEVOPS_DEPLOYMENT.md` | Deployment, Docker, AWS, infrastructure |

---

## CLASSIFICATION EXAMPLES

### Example 1
**User:** "The BUY chip is not showing green when it should"

**Classification:** Category 1 (Frontend UI / Watchlist UI / Signal Chip Issues)
**Action:** Execute **Watchlist Audit (Autonomous)** workflow immediately

---

### Example 2
**User:** "Alerts are not being sent when RSI < 40"

**Classification:** Category 2 (Backend Strategy / Alert Logic / Signal Monitor)
**Action:** Execute **Backend Strategy & Alerts Audit (Autonomous)** workflow immediately

---

### Example 3
**User:** "The Watchlist shows BUY but backend logs show WAIT"

**Classification:** Category 4 (Full System Integration Issues)
**Action:** Execute **Watchlist + Backend Full Integration Audit** (both workflows in sequence)

---

### Example 4
**User:** "Add a new column to show volume ratio in the Watchlist"

**Classification:** Category 6 (Frontend Code Changes / New Features)
**Action:** Execute **Frontend Change (Validated e2e)** workflow immediately

---

### Example 5
**User:** "Docker container keeps crashing on AWS"

**Classification:** Category 3 (DevOps / AWS / Deployment / Docker)
**Action:** Execute **DevOps Deployment Fix (Autonomous)** workflow immediately

---

## IMPLEMENTATION NOTES

This router must be applied on **EVERY user request automatically**.

The classification should happen **immediately** upon receiving the user's request, before any code changes or patches are made.

If a request doesn't clearly fit into one category, use the following priority:
1. If it mentions UI/frontend → Category 1 or 6
2. If it mentions backend/logic/alerts → Category 2
3. If it mentions both → Category 4
4. If it mentions deployment/infrastructure → Category 3
5. If it's a general audit request → Category 5

---

## QUICK DECISION TREE

```
User Request
    ↓
Does it mention UI/button/chip/display?
    ↓ YES → Category 1 (Watchlist Audit)
    ↓ NO
Does it mention backend/alert/signal/strategy?
    ↓ YES → Category 2 (Backend Audit)
    ↓ NO
Does it mention deployment/docker/aws/vercel?
    ↓ YES → Category 3 (DevOps)
    ↓ NO
Does it mention both frontend AND backend?
    ↓ YES → Category 4 (Full Integration)
    ↓ NO
Is it a general audit/validation request?
    ↓ YES → Category 5 (Watchlist Audit)
    ↓ NO
Is it a new frontend feature?
    ↓ YES → Category 6 (Frontend Change)
    ↓ NO
→ Default to Category 1 (Watchlist Audit) for safety
```

---

## ENFORCEMENT

**This router is MANDATORY and must be applied automatically.**

**No exceptions.**
**No questions.**
**No delays.**

**Activate the correct workflow immediately upon request classification.**














