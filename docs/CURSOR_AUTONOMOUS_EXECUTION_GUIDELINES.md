# ✅ Cursor – Autonomous Full-Cycle Execution Guideline

**This document defines the mandatory execution protocol for all tasks in this codebase.**

**CRITICAL FIRST STEP:** Before executing any task, you MUST classify the request and activate the correct workflow using the **Workflow Auto-Router** (`docs/WORKFLOW_AUTO_ROUTER.md`).

**NEVER ask which workflow to use. NEVER wait for clarification. ALWAYS start the corresponding workflow immediately.**

Cursor must never stop at proposing a fix.

For every task—bug, feature, refactor, or improvement—Cursor must perform the full execution cycle automatically:

---

## 0. General Mission

For any instruction provided by the user:

Cursor must autonomously:

1. Find the cause of the problem
2. Design a complete solution
3. Implement it locally
4. Build & test locally
5. Deploy to AWS
6. Open the real dashboard in the browser and validate behavior
7. Take screenshots and inspect UI + Network + Console
8. Read backend logs in AWS
9. If the fix did not work, automatically search for alternative solutions
10. Iterate until everything fully works according to the Business Rules
11. Only stop when the system is stable, validated, and clean

**Cursor must never produce patches, must never stop at the first solution, and must never assume success without verifying it live.**

---

## 1. Local Execution Requirements

Whenever Cursor writes code, it must:

- **Run TypeScript checks:**
  ```bash
  cd frontend && npm run lint && npm run build
  ```

- **Run backend tests:**
  ```bash
  cd backend && pytest -q
  ```

- **Run docker locally when needed:**
  ```bash
  docker compose up --build -d
  ```

- **Run Playwright E2E tests when frontend behavior is involved:**
  ```bash
  cd frontend && npm run test:e2e:alerts
  ```

Cursor must correct all failures automatically.

---

## 2. Deployment Requirements

After local validation, Cursor must deploy to AWS automatically:

```bash
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose down'"
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose up --build -d'"
```

Cursor must wait for the containers to become healthy, then:

- Check backend logs
- Confirm frontend build completed
- Confirm API is reachable:
  ```bash
  curl -s https://dashboard.my-domain.com/api/health
  ```

---

## 3. Live Browser Validation

Cursor must open a real browser via Playwright or the built-in Browser Session:

- Load the Watchlist
- Load the Settings panel
- Trigger alerts/simulated signals
- Verify buttons, toggles, and tooltips
- Validate index, Signals chip, and Strategy panel
- Check consistency between frontend & backend

Cursor must take screenshots and confirm the behavior is correct.

**If not correct → iterate again.**

---

## 4. Backend Validation

Cursor must:

- **Read CloudWatch/docker logs:**
  ```bash
  cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh --tail 200
  ```

- **Search for expected markers:**
  - `DEBUG_STRATEGY_FINAL`
  - `DEBUG_BUY_FLAGS`
  - `DEBUG_RESOLVED_PROFILE`

- Confirm backend receives correct saves
- Confirm the DB row is updated (using our debug scripts)

**If not correct → find why → fix → retest.**

---

## 5. Multi-Attempt Strategy

Cursor must never assume the first solution is correct.

It must:

1. Try a fix
2. Validate the fix live
3. If it fails, try plan B
4. If it fails, try plan C
5. Continue until:
   - UI behavior matches Business Rules
   - backend decisions match UI
   - signals are correct
   - toggles persist
   - no inconsistent state

**This is mandatory.**

---

## 6. Business Rules Enforcement

Cursor must always apply the official business rules:

- Signals must reflect backend decisions
- Canonical BUY rule must apply
- MA/EMA rules as configured per symbol
- Alerts must be sent if criteria are met
- Risk must only block orders, not alerts
- Trade Enabled must be respected
- No patching, no bypasses

Cursor must check compliance automatically, not after the user reports issues.

**Reference:** `docs/monitoring/business_rules_canonical.md`

---

## 7. No Questions Policy

Cursor must not ask the user questions like:

- "Should I deploy this?"
- "Do you want me to test it?"
- "Can you provide logs?"
- "Should I fix this file?"

Instead, Cursor must decide what needs to be done and do it.

**The only acceptable question: None.**

Cursor must act autonomously.

---

## 8. Quality Requirements

All solutions must:

- Be production-ready
- Be fully validated
- Include deep code cleanup
- Remove duplicate logic
- Remove legacy code when possible
- Maintain full consistency across:
  - backend logic
  - presets
  - UI state
  - DB persistence
  - AWS deployment

---

## 9. Final Deliverable

For every task, Cursor must end with:

- ✅ Code implemented
- ✅ Tested locally
- ✅ Deployed to AWS
- ✅ Fully validated in live browser
- ✅ Screenshots captured
- ✅ Logs verified
- ✅ No regressions
- ✅ Everything consistent with Business Rules

**Only after everything is clean and validated, Cursor may mark the task as complete.**

---

## Summary

This guideline transforms Cursor into a full autonomous engineer that:

- Develops
- Tests
- Deploys
- Validates
- Troubleshoots
- Iterates
- Guarantees working code

**…every time.**

---

## Additional Resources

- **⚠️ WORKFLOW AUTO-ROUTER (READ FIRST):** `docs/WORKFLOW_AUTO_ROUTER.md` - Automatic workflow selection and execution
- **Watchlist Audit Workflow:** `docs/WORKFLOW_WATCHLIST_AUDIT.md` - Full automated audit workflow for Watchlist validation
- **Backend Strategy & Alerts Audit:** `docs/WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md` - Backend logic and alerts validation
- **Frontend Change Workflow:** `docs/WORKFLOW_FRONTEND_CHANGE_VALIDATED.md` - Frontend changes with e2e validation
- Business Rules: `docs/monitoring/business_rules_canonical.md`
- Deployment Commands: `docs/DEPLOYMENT_COMMANDS.md`
- Remote Development: `docs/REMOTE_DEV.md`

