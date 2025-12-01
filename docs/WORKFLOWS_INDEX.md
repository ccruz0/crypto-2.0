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

### 2b. **Strict Watchlist Audit** ⚡ NEW
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

## 🔄 Workflow Selection Guide

| User Request Type | Workflow | Document |
|------------------|----------|----------|
| UI/Button/Chip issues | Watchlist Audit | `WORKFLOW_WATCHLIST_AUDIT.md` |
| Strict audit/validation | Strict Watchlist Audit | `WORKFLOW_STRICT_WATCHLIST_AUDIT.md` |
| Backend logic/alerts | Backend Strategy & Alerts Audit | `WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md` |
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
- [Autonomous Execution Guidelines](./CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md)

