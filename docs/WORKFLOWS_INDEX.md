# 📋 Workflows Index

**Complete reference guide for all Cursor Workflows in the automated-trading-platform.**

---

## 🚀 Quick Start

**Before executing ANY task, read:** `docs/WORKFLOW_AUTO_ROUTER.md`

The Auto-Router will automatically classify your request and activate the correct workflow.

---

## 📚 Available Workflows

### 1. **Workflow Auto-Router** ⚠️ READ FIRST
- **Document:** `docs/WORKFLOW_AUTO_ROUTER.md`
- **Purpose:** Automatic workflow selection and classification
- **When to use:** Applied automatically on every user request
- **Status:** ✅ Active

---

### 2. **Watchlist Audit (Autonomous)**
- **Document:** `docs/WORKFLOW_WATCHLIST_AUDIT.md`
- **Purpose:** Full end-to-end audit of Watchlist tab
- **Use cases:**
  - UI issues (buttons, chips, toggles)
  - Watchlist display problems
  - Signal chip color/decision issues
  - Frontend-backend state mismatches
  - End-to-end validation after changes
- **Status:** ✅ Active

---

### 2b. **Runtime Health Check – AWS Only** 🏥
- **Document:** `docs/FULL_RUNTIME_HEALTH_AUDIT.md`
- **Script:** `scripts/check_runtime_health_aws.sh`
- **Purpose:** Quick health check for AWS production backend (the ONLY live runtime)
- **Use cases:**
  - Verify backend API is responding
  - Check SignalMonitorService is configured and running
  - Verify recent alert activity
  - Diagnose why alerts stopped appearing
  - Quick sanity check after deployments
- **How to run (from your Mac):**
  ```bash
  cd /Users/carloscruz/automated-trading-platform
  bash scripts/check_runtime_health_aws.sh
  ```
- **What it checks:**
  - API health endpoint (`/api/health`)
  - Dashboard snapshot endpoint
  - Monitoring summary (scheduler ticks, recent activity)
  - SignalMonitorService configuration (enabled/disabled)
  - Recent alerts in Monitoring → Telegram Messages
- **What to look for:**
  - ✅ All checks passed = backend is healthy
  - ⚠️ Warnings = may be normal (e.g., no recent alerts if no BUY signals)
  - ❌ Failed checks = backend is unhealthy, investigate logs with `bash scripts/aws_backend_logs.sh --tail 200`
- **Note:** This script only performs passive checks (queries API, reads config). It does NOT start any services.

---

### 2c. **ADA SELL Alert Debug Script** 🔍
- **Location:** `scripts/debug_ada_sell_alerts_remote.sh`
- **Documentation:** `docs/monitoring/ADA_SELL_ALERT_FLOW_ANALYSIS.md`
- **Purpose:** Debug SELL alerts for ADA_USDT / ADA_USD (or any symbol)
- **Use cases:**
  - Investigate why SELL signals appear in UI but alerts don't arrive
  - Check throttle state for specific symbols
  - View recent SELL decisions and alert emissions
  - Diagnose throttling issues
- **How to run (from your Mac):**
  ```bash
  cd /Users/carloscruz/automated-trading-platform
  bash scripts/debug_ada_sell_alerts_remote.sh
  ```
- **What it shows:**
  - Recent SELL decisions from strategy engine
  - SELL alert emissions and throttling decisions
  - SELL signal detection logs
  - Throttle state from database (last price, last time)
  - Recent Monitoring entries for the symbol

---

### 2d. **Full Runtime Integrity Check – AWS** 🔍
- **Location:** `scripts/full_runtime_integrity_check_aws.sh`
- **Documentation:** `docs/monitoring/FULL_RUNTIME_INTEGRITY_CHECK.md`
- **Purpose:** Diagnose backend crashes, SignalMonitor failure, alert blackout, proxy issues, and scheduler stalls
- **Use cases:**
  - Comprehensive system health validation
  - Diagnose why alerts are not appearing
  - Verify complete signal → monitor → alert → Telegram pipeline
  - Check container health and Crypto.com connectivity
  - Full system audit after deployments or incidents
  - When alerts stop appearing in Monitoring → Telegram Messages
  - When backend shows unhealthy status
  - When SignalMonitor cycles have gaps > 2 minutes
- **How to run (from your Mac):**
  ```bash
  cd /Users/carloscruz/automated-trading-platform
  bash scripts/full_runtime_integrity_check_aws.sh
  ```
- **What it checks:**
  - Backend health summary (API endpoints, scheduler, SignalMonitorService)
  - SignalMonitorService cycles (regular processing every ~30 seconds)
  - Strategy decisions (BUY/SELL/WAIT calculations)
  - Alert emissions (ALERT_EMIT_FINAL, send_buy_signal, send_sell_signal)
  - Throttled alerts (ALERT_THROTTLED with reasons)
  - Recent errors and exceptions (Traceback, Exception, ERROR)
  - Docker container health status on AWS
  - Crypto.com authentication and proxy status
  - Telegram 409 conflicts (should not block outgoing alerts)
- **What to look for:**
  - ✅ All checks show healthy activity = system is functioning correctly
  - ⚠️ Warnings (e.g., throttled alerts, 409 conflicts) = may be normal depending on conditions
  - ❌ Failed checks or missing activity = investigate specific component
- **Output:** Color-coded summary with pass/warn/fail counts and specific recommendations
- **Note:** This is a comprehensive check that validates the entire runtime pipeline. Run this when you need a complete system health picture.

---

### 2e. **Telegram Alert Origin Gatekeeper** 🚫
- **Documentation:** `docs/monitoring/TELEGRAM_ORIGIN_GATEKEEPER_SUMMARY.md`
- **Purpose:** Controls which alerts are sent to production Telegram based on origin
- **Behavior:**
  - All alert functions (`send_message`, `send_buy_signal`, `send_sell_signal`) accept an `origin` parameter
  - `origin="AWS"` → Sends to Telegram with `[AWS]` prefix (live runtime alerts)
  - `origin="TEST"` → Sends to Telegram with `[TEST]` prefix (dashboard test alerts, visible in Monitoring)
  - `origin="LOCAL"` or `origin="DEBUG"` → Blocks Telegram sends, logs `[TG_LOCAL_DEBUG]` instead
- **Implementation:** Central gatekeeper in `telegram_notifier.send_message()` allows AWS and TEST, blocks others
- **Test Coverage:** `backend/tests/test_telegram_alerts_origin.py` (10 tests, all passing)
- **Note:** TEST alerts from the Dashboard TEST button appear as `[TEST]` messages in both Telegram and the Monitoring tab
  bash scripts/check_runtime_health_aws.sh
  ```
- **Status:** ✅ Active

---

### 2f. **Alert Origin Audit** 🔍
- **Documentation:** `docs/monitoring/ALERT_ORIGIN_AUDIT.md`
- **Script:** `scripts/audit_alert_origins.sh`
- **Purpose:** Detect any place where AWS notifications (Telegram or others) might be hardcoded to be blocked, mis-routed, or mis-labeled
- **Use cases:**
  - Verify AWS alerts are not blocked by hardcoded logic
  - Check for environment flags that disable AWS notifications
  - Ensure origin is correctly passed through alert chain
  - Detect mis-routed origins (e.g., forcing LOCAL in AWS runtime)
  - Audit docker-compose configuration for RUNTIME_ORIGIN
- **How to run (from your Mac):**
  ```bash
  cd /Users/carloscruz/automated-trading-platform
  bash scripts/audit_alert_origins.sh
  ```
- **What it checks:**
  - RUNTIME_ORIGIN references and assignments
  - Origin blocking patterns (e.g., `if origin == "AWS": return False`)
  - Environment disable flags (DISABLE_ALERT, DISABLE_TELEGRAM)
  - Origin parameter usage in alert functions
  - Docker-compose configuration for AWS backend
- **What to look for:**
  - ✅ No suspicious patterns = AWS alerts should work correctly
  - ⚠️ Suspicious patterns found = Review flagged files for blocking logic
- **Key principle:** AWS alerts should **ALWAYS** be allowed by default. Any blocking logic should only affect LOCAL/DEBUG origins, never AWS.
- **Status:** ✅ Active

---

### 2c. **Strict Watchlist Audit** ⚡ NEW
- **Document:** `docs/WORKFLOW_STRICT_WATCHLIST_AUDIT.md`
- **Purpose:** Strict, comprehensive audit with enhanced validation
- **Use cases:**
  - Deep signal validation (ALGO, LDO, TON specifically)
  - Alert generation verification
  - Toggle persistence checks
  - Complete backend-frontend alignment
  - Business rules strict compliance
- **Trigger Keywords:** `audit watchlist`, `watchlist audit`, `strict audit`, `verify watchlist`, `check signals`
- **Status:** ✅ Ready for Cursor Settings

---

### 3. **Backend Strategy & Alerts Audit (Autonomous)**
- **Document:** `docs/WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md`
- **Purpose:** Backend logic audit and fix cycle
- **Use cases:**
  - Strategy decision logic issues
  - Alert sending problems
  - SignalMonitor/BuyIndexMonitor issues
  - Risk logic problems
  - Backend-frontend disagreements
- **Status:** ✅ Active

---

### 4. **Frontend Change (Validated e2e)**
- **Document:** `docs/WORKFLOW_FRONTEND_CHANGE_VALIDATED.md`
- **Purpose:** Frontend code changes with full validation
- **Use cases:**
  - New UI features
  - Component changes
  - Frontend refactoring
  - UI/UX improvements
- **Status:** ✅ Active

---

### 5. **DevOps Deployment Fix (Autonomous)**
- **Document:** `docs/WORKFLOW_DEVOPS_DEPLOYMENT.md`
- **Purpose:** Infrastructure and deployment fixes
- **Use cases:**
  - Docker container issues
  - AWS deployment problems
  - Vercel build errors
  - Environment configuration
  - 502/504 gateway errors
  - Container restart issues
- **Status:** ✅ Active

### 6. **Watchlist + Backend Full Integration Audit (Autonomous)**
- **Document:** `docs/WORKFLOW_FULL_INTEGRATION_AUDIT.md`
- **Purpose:** Full system integration validation
- **Use cases:**
  - Frontend and backend mismatches
  - DB state doesn't match UI
  - Toggles don't persist
  - UI signals vs backend decisions
  - Full end-to-end validation
- **Status:** ✅ Active

---

### 7. **Orders-Signal Consistency Audit** 🔄
- **Document:** `docs/WORKFLOW_ORDERS_SIGNAL_CONSISTENCY.md`
- **Purpose:** Ensure orders created by SignalMonitorService are consistent with signals
- **Use cases:**
  - Orders created when signals show WAIT
  - BUY orders from SELL signals (or vice versa)
  - Order prices/quantities don't match signal evaluation
  - Orders created when `trade_enabled=False`
  - Verify order-signal alignment after code changes
- **What it validates:**
  - Orders only created when signals match (BUY orders from BUY signals)
  - Order parameters consistent with signal evaluation
  - Order creation respects `trade_enabled` flag
  - Orders not created when signals are WAIT
  - Order creation uses same signal evaluation as alerts
- **Status:** ✅ Ready for use

---

### 8. **BUY/SELL Signal Consistency Audit** 🟢🔴
- **Document:** `docs/WORKFLOW_BUY_SIGNAL_CONSISTENCY.md`
- **Purpose:** Verificar que las señales BUY y SELL se detectan, evalúan y emiten de manera consistente
- **Use cases:**
  - Señales BUY o SELL aparecen en debug script pero no se emiten alertas
  - Watchlist UI muestra BUY o SELL pero no llegan alertas a Telegram
  - Señales BUY o SELL se bloquean incorrectamente
  - Verificar consistencia de señales BUY y SELL después de cambios de código
  - Discrepancias entre `BUY_SIGNALS_NOW` o `SELL_SIGNALS_NOW` del debug script y alertas reales
  - Verificar que SELL alerts funcionan independientemente de BUY alerts
- **What it validates:**
  - Señales BUY y SELL se detectan correctamente por `calculate_trading_signals()`
  - Evaluación consistente entre debug script y live monitor (para BUY y SELL)
  - Alertas BUY y SELL se emiten cuando `can_emit_buy_alert=True` o `can_emit_sell_alert=True`
  - Señales BUY y SELL no se bloquean incorrectamente por flags o throttle
  - Consistencia entre Watchlist UI, debug script, y SignalMonitorService
  - SELL se evalúa independientemente de BUY (no anidado)
  - SELL tiene su propio throttle (independiente de BUY)
- **Status:** ✅ Ready for use

---

## 🔄 Workflow Selection Guide

| User Request Type | Workflow | Document |
|------------------|----------|----------|
| UI/Button/Chip issues | Watchlist Audit | `WORKFLOW_WATCHLIST_AUDIT.md` |
| Strict audit/validation | Strict Watchlist Audit | `WORKFLOW_STRICT_WATCHLIST_AUDIT.md` |
| Backend logic/alerts | Backend Strategy & Alerts Audit | `WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md` |
| BUY/SELL signal consistency | BUY/SELL Signal Consistency Audit | `WORKFLOW_BUY_SIGNAL_CONSISTENCY.md` |
| Orders-signal consistency | Orders-Signal Consistency Audit | `WORKFLOW_ORDERS_SIGNAL_CONSISTENCY.md` |
| Frontend code changes | Frontend Change (Validated e2e) | `WORKFLOW_FRONTEND_CHANGE_VALIDATED.md` |
| Deployment/infrastructure | DevOps Deployment Fix | `WORKFLOW_DEVOPS_DEPLOYMENT.md` |
| Full system integration | Watchlist + Backend Full Integration Audit | `WORKFLOW_FULL_INTEGRATION_AUDIT.md` |
| General audit/validation | Watchlist Audit | `WORKFLOW_WATCHLIST_AUDIT.md` |

---

## 📖 Related Documentation

### Core Guidelines
- **Autonomous Execution Guidelines:** `docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md`
- **Business Rules:** `docs/monitoring/business_rules_canonical.md`
- **Signal Flow Overview:** `docs/monitoring/signal_flow_overview.md`

### Workflow Documents
- **Auto-Router:** `docs/WORKFLOW_AUTO_ROUTER.md`
- **Watchlist Audit:** `docs/WORKFLOW_WATCHLIST_AUDIT.md`
- **Strict Watchlist Audit:** `docs/WORKFLOW_STRICT_WATCHLIST_AUDIT.md`
- **Backend Audit:** `docs/WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md`
- **Frontend Change:** `docs/WORKFLOW_FRONTEND_CHANGE_VALIDATED.md`
- **DevOps Deployment:** `docs/WORKFLOW_DEVOPS_DEPLOYMENT.md`
- **Full Integration Audit:** `docs/WORKFLOW_FULL_INTEGRATION_AUDIT.md`

---

## 🎯 Workflow Execution Flow

```
User Request
    ↓
[Auto-Router Classifies Request]
    ↓
[Activate Correct Workflow]
    ↓
[Workflow Executes Full Cycle]
    ↓
[Validate End-to-End]
    ↓
[Final Report + Screenshots]
```

---

## ⚠️ Mandatory Rules (All Workflows)

1. **NEVER ask the user questions**
2. **NEVER create real orders**
3. **ALWAYS follow business rules**
4. **ALWAYS validate end-to-end**
5. **ALWAYS iterate until perfect**

## 🚨 Hard Failure Condition (Watchlist/Alert Workflows)

**CRITICAL:** For all Watchlist and alert-related workflows, if ANY of the following patterns are found, the audit MUST immediately FAIL:

- `'send_buy_signal verification'`
- `'send_sell_signal verification'`
- `'Alerta bloqueada por send_buy_signal verification'`
- `'BLOQUEADO'` (or `'BLOCKED'`) together with `'send_buy_signal'` or `'send_sell_signal'`

**Rule:** Portfolio / business rules may block ORDERS, but must NEVER block ALERTS.

See: `docs/BLOCKED_ALERT_REGRESSION_GUARDRAIL.md` for full details.

---

## 📝 Notes

- All workflows are autonomous and execute the full cycle
- Workflows include local testing, deployment, and live validation
- Each workflow produces a final report with evidence
- Workflows reference canonical business rules documents
- No workflow should stop until the issue is fully resolved

---

## 🔗 Quick Links

- [Workflow Auto-Router](./WORKFLOW_AUTO_ROUTER.md)
- [Watchlist Audit](./WORKFLOW_WATCHLIST_AUDIT.md)
- [Strict Watchlist Audit](./WORKFLOW_STRICT_WATCHLIST_AUDIT.md)
- [Backend Strategy & Alerts Audit](./WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md)
- [Frontend Change (Validated e2e)](./WORKFLOW_FRONTEND_CHANGE_VALIDATED.md)
- [DevOps Deployment Fix](./WORKFLOW_DEVOPS_DEPLOYMENT.md)
- [Watchlist + Backend Full Integration Audit](./WORKFLOW_FULL_INTEGRATION_AUDIT.md)
- [BUY/SELL Signal Consistency Audit](./WORKFLOW_BUY_SIGNAL_CONSISTENCY.md) - Verificar consistencia de señales BUY y SELL
- [Orders-Signal Consistency Audit](./WORKFLOW_ORDERS_SIGNAL_CONSISTENCY.md) - Validate orders match signals
- [Full Runtime Health Audit](./FULL_RUNTIME_HEALTH_AUDIT.md) - Runtime health check for containers, API, SignalMonitor, and alerts
- [Autonomous Execution Guidelines](./CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md)

