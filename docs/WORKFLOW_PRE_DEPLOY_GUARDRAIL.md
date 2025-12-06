# Pre-Deploy Guardrail Workflow

**Status:** ✅ Active  
**Purpose:** HARD PRE-DEPLOY GATE - Blocks deployments if alert regression patterns are detected

---

## Overview

This workflow acts as a mandatory pre-deployment gate that runs the Alert Regression Guardrail before ANY deployment (backend, frontend, or full platform).

**Rule:** If ANY alert-blocking regression is detected, deployment is BLOCKED until the regression is fixed.

---

## Trigger Keywords

This workflow automatically triggers when the user mentions (case-insensitive):

- `deploy`
- `deploy aws`
- `deploy backend`
- `deploy frontend`
- `push to prod`
- `release watchlist`

---

## Execution Flow

```
USER REQUEST → RUN GUARDRAIL → CHECK RESULT
                                    ↓
                            ┌───────┴───────┐
                            │               │
                        PASSED           FAILED
                            │               │
                            ↓               ↓
                    PROCEED WITH        ENTER FIX MODE
                    DEPLOYMENT         → FIX CODE
                                            → REBUILD
                                            → RE-RUN GUARDRAIL
                                            → LOOP UNTIL PASS
```

---

## Step-by-Step Process

### 1. Run Guardrail Script

**Command:**
```bash
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && python3 -m backend.scripts.assert_no_blocked_alert_regressions'"
```

**What it checks:**
- Docker logs on AWS for blocked alert patterns
- Patterns searched:
  - `'send_buy_signal verification'`
  - `'send_sell_signal verification'`
  - `'Alerta bloqueada por send_buy_signal verification'`
  - `'BLOQUEADO'` (or `'BLOCKED'`) together with `'send_buy_signal'` or `'send_sell_signal'`

### 2. If Guardrail FAILS

**Enter FIX MODE automatically:**

1. **Search for regression patterns:**
   ```bash
   grep -r "ALERTA BLOQUEADA\|ALERT BLOCKED\|send_buy_signal verification" backend/app/services/
   ```

2. **Check critical files:**
   - `backend/app/services/signal_monitor.py`
   - `backend/app/services/telegram_notifier.py`

3. **Remove blocking logic:**
   - Remove ANY logic blocking alerts after `decision=BUY`
   - Remove ANY `return` statements in alert paths after conditions are met
   - Remove ANY portfolio risk checks that block alerts (they should only block orders)
   - Remove ANY `raise`/`return` inside `send_buy_signal()` / `send_sell_signal()`

4. **Restore canonical flow:**
   - Alerts are NEVER blocked by portfolio risk
   - Alerts are NEVER blocked by verification inside send_* functions
   - Alerts are ONLY blocked by:
     - `alert_enabled=False` (checked BEFORE calling send functions)
     - `buy_alert_enabled=False` / `sell_alert_enabled=False` (checked BEFORE calling send functions)
     - Throttle rules (checked BEFORE calling send functions)

5. **Rebuild backend locally:**
   ```bash
   cd backend
   pytest -q  # Run tests
   ```

6. **Re-run guardrail on AWS:**
   ```bash
   sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && python3 -m backend.scripts.assert_no_blocked_alert_regressions'"
   ```

7. **Loop until guardrail PASSES:**
   - DO NOT deploy until guardrail passes
   - Continue fixing and re-testing until clean

### 3. If Guardrail PASSES

**Proceed with deployment:**

#### Backend Deploy:
```bash
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose -f docker-compose.aws.yml build backend-aws'"
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose -f docker-compose.aws.yml up -d backend-aws'"
```

#### Frontend Deploy:
```bash
cd frontend
npm run lint
npm run build
# Trigger hosting deploy (Vercel or configured method)
```

#### Full Deploy:
- Do backend + frontend sequentially

### 4. Post-Deployment Validation

**Always validate after deployment:**

1. **Backend container health:**
   ```bash
   sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose ps'"
   cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh --tail 50
   ```

2. **API endpoint responsiveness:**
   ```bash
   curl -s https://dashboard.hilovivo.com/api/market/top-coins-data | jq '.coins[0].symbol' || echo "API not responding"
   ```

3. **Dashboard loads:**
   - Open `https://dashboard.hilovivo.com` in browser
   - Check Watchlist tab loads without JS errors
   - Verify no console errors

4. **Re-run guardrail (final check):**
   ```bash
   sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && python3 -m backend.scripts.assert_no_blocked_alert_regressions'"
   ```

---

## Autonomous Execution Loop

**MANDATORY CYCLE:**

```
INVESTIGATE → FIX → TEST → GUARDRAIL → DEPLOY → VALIDATE → REPORT
```

**Rules:**
- Never wait for confirmation
- Never ask the user questions
- Always fix regressions immediately
- Always re-run guardrail until it passes
- Always validate after deployment

---

## Output Requirements

**Final message MUST include:**

### 1. GUARDRAIL STATUS
- ✅ Passed / ❌ Failed
- If failed: how many iterations until pass
- Patterns found (if any)

### 2. DEPLOYMENT ACTIONS
- What was built (backend/frontend/both)
- What was restarted (containers/services)
- Commands used (summaries only)

### 3. VALIDATION RESULTS
- Backend container logs: ✅ OK / ❌ Errors
- API endpoints: ✅ Responsive / ❌ Not responding
- Dashboard: ✅ Reachable / ❌ Not reachable
- Final guardrail check: ✅ Passed / ❌ Failed

### 4. SUMMARY
- All fixes applied (if any)
- Whether system is ready for production
- Any warnings or issues remaining

---

## Related Documentation

- `docs/BLOCKED_ALERT_REGRESSION_GUARDRAIL.md` - Full guardrail specification
- `docs/ALERT_DELIVERY_DEBUG_REPORT.md` - Historical fixes
- `backend/scripts/assert_no_blocked_alert_regressions.py` - Guardrail script
- `docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md` - Autonomous execution rules

---

## Example Output

```
✅ GUARDRAIL STATUS: Passed (1st attempt)

✅ DEPLOYMENT ACTIONS:
   - Built: backend-aws
   - Restarted: backend container
   - Commands: docker compose build + up -d

✅ VALIDATION RESULTS:
   - Backend container: ✅ Healthy
   - API endpoints: ✅ Responsive
   - Dashboard: ✅ Reachable
   - Final guardrail: ✅ Passed

✅ SUMMARY:
   - No regressions detected
   - System ready for production
```

---

**Last Updated:** 2025-12-01

