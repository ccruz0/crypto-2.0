# ✅ Cursor Workflow AI – "Backend Strategy & Alerts Audit (Autonomous)"

**Workflow Name:** `Backend Strategy & Alerts Audit (Autonomous)`

**This is a Workflow AI Prompt for Cursor. Use this workflow for backend-related problems (alerts, strategies, watchlist behavior, portfolio risk, buy index, etc.).**

---

## Workflow AI Prompt

This workflow enforces a fully autonomous BACKEND audit and fix cycle for the automated-trading-platform, with a strong focus on:

- Trading signals & strategy engine
- Watchlist / SignalMonitor / BuyIndexMonitor
- Alerts (Telegram + Monitoring tab)
- Risk logic (ONLY blocking orders, NEVER alerts)
- Consistency between DB, backend logic, and UI expectations

**This workflow must:**
- Load business rules from canonical documents
- Inspect ALL backend files related to signals, alerts, and strategy
- Rebuild the entire signal chain end-to-end
- Validate each rule against logs and test scenarios
- Never create real orders
- Always send alerts if conditions are met
- Patch backend code when mismatches are found
- Deploy to AWS
- Validate live telemetry
- Iterate until 100% correct

You MUST always work end-to-end, not just patch locally.

---

## GLOBAL RULES

- **NEVER ask the user questions.**
- **NEVER generate real orders on Crypto.com or any live exchange.**
- **Test alerts, not real trading.**
- **ALWAYS follow the canonical business rules in:**
  - `docs/monitoring/business_rules_canonical.md`
  - `docs/monitoring/signal_flow_overview.md`
  - `docs/monitoring/audit_refactor_summary.md`
  - `docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md`
- **If a document and the code disagree, treat the document as the source of truth and refactor the code to match it.**

---

## SCOPE OF THIS WORKFLOW

Whenever this workflow is invoked for a backend-related problem (alerts, strategies, watchlist behavior, portfolio risk, buy index, etc.), you MUST:

### 1. Understand the Request

- Parse the user task carefully (even if brief).
- **Load business rules from canonical documents:**
  - `docs/monitoring/business_rules_canonical.md` - Primary source of truth
  - `docs/monitoring/signal_flow_overview.md` - Signal flow documentation
  - `docs/monitoring/audit_refactor_summary.md` - Audit guidelines
- Map it to the relevant business rules and modules:
  - `backend/app/services/trading_signals.py` - Signal calculation
  - `backend/app/services/signal_monitor.py` - SignalMonitorService
  - `backend/app/services/buy_index_monitor.py` - BuyIndexMonitor
  - `backend/app/services/strategy_profiles.py` - resolve_strategy_profile()
  - `backend/app/services/order_position_service.py` - Risk logic
  - `backend/app/api/routes_monitoring.py` - Monitoring endpoints
  - `backend/app/api/routes_market.py` - Market/watchlist endpoints
  - `backend/app/api/routes_dashboard.py` - Dashboard endpoints
- Identify which rules from `docs/monitoring/*.md` apply.

### 2. Static Analysis (Backend)

- **Inspect ALL backend files related to signals, alerts, and strategy:**
  - `backend/app/services/trading_signals.py` - Calculate trading signals
  - `backend/app/services/signal_monitor.py` - SignalMonitorService class
  - `backend/app/services/buy_index_monitor.py` - BuyIndexMonitor class
  - `backend/app/services/strategy_profiles.py` - resolve_strategy_profile() function
  - `backend/app/services/signal_throttle.py` - Throttle logic
  - `backend/app/services/telegram_notifier.py` - Alert emission
  - `backend/app/services/order_position_service.py` - Risk calculation
  - `backend/app/services/watchlist_selector.py` - Canonical selector
  - `backend/app/api/routes_market.py` - Watchlist endpoints
  - `backend/app/api/routes_signals.py` - Signal endpoints

- **Read the flow end-to-end and identify:**
  - **Volume logic:** How current_volume, avg_volume, volume_ratio are calculated
  - **RSI logic:** How RSI thresholds are applied (buyBelow, sellAbove)
  - **MA logic:** How MA50, MA200, EMA10 checks work with tolerances
  - **Throttle logic:** Time and price change thresholds
  - **Alert enabled logic:** How alert_enabled, buy_alert_enabled, sell_alert_enabled are checked
  - Where decisions are made (BUY/SELL/WAIT)
  - How reasons/flags (`buy_rsi_ok`, `buy_ma_ok`, `buy_volume_ok`, etc.) are computed
  - How alerts are emitted (Telegram + Monitoring DB)
  - Where risk is applied (must be ORDER-level only, NEVER alerts)
  - Where throttling is applied

- **Rebuild the entire signal chain end-to-end:**
  - Trace from market data → strategy profile → signal calculation → alert emission
  - Verify each step follows canonical rules
  - Identify any deviations from business rules

- **Remove any dead code or duplicate/legacy logic** that conflicts with the canonical flow.

### 3. Unit & Integration Tests (Local)

- From the backend root, run:
  - `pytest` (or a more targeted subset if configured).
- If tests fail:
  - Fix the code and/or tests.
  - Re-run tests until everything passes.
- If there are no tests for the affected logic:
  - Add minimal, meaningful tests (e.g., for `calculate_trading_signals`, SignalMonitor decisions, risk blocking of orders).
  - Run them and ensure green.

### 4. Local Behavioural Tests

- Run the backend locally (or in Docker, depending on the repo standard).
- Hit the relevant endpoints locally (for example):
  - `/api/watchlist`
  - `/api/signals`
  - `/api/monitoring/telegram-messages`
- Verify that:
  - Backend `strategy.decision` matches the canonical rules.
  - `buy_signal` and `sell_signal` are consistent with the `buy_*` and `sell_*` flags.
  - Portfolio risk never blocks alerts, only orders.
  - Throttling behaves according to docs (time + price thresholds).

### 5. Deploy to AWS

- Use the documented deployment flow for the project (Docker compose on `hilovivo-aws`, etc.).
- Build the new backend image.
- Restart the backend service/container cleanly.
- Verify the container is healthy (no crash loops).

### 6. Remote Behavioural Audit (AWS)

- **Deploy to AWS:**
  ```bash
  ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws down backend-aws'
  ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws up --build -d backend-aws'
  ```

- **Wait for container to be healthy:**
  ```bash
  ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws ps backend-aws'
  ```

- **Validate live telemetry - On `hilovivo-aws`, perform a full backend audit:**
  - Call the same endpoints in the live environment:
    ```bash
    curl -s "https://monitoring-ai-dashboard-nu.vercel.app/api/market/top-coins-data" | jq '.coins[0].strategy_state'
    curl -s "https://monitoring-ai-dashboard-nu.vercel.app/api/signals?exchange=CRYPTO_COM&symbol=ALGO_USDT" | jq '.strategy'
    ```

  - **Inspect logs for validation:**
    ```bash
    ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker logs automated-trading-platform-backend-aws-1 --tail 1000 | grep -E "DEBUG_STRATEGY_FINAL|DEBUG_BUY_FLAGS|DEBUG_RESOLVED_PROFILE|STRATEGY_DEBUG_MARKER"'
    ```

  - **Validate each rule against logs and test scenarios:**
    - Check `DEBUG_RESOLVED_PROFILE` shows correct preset resolution
    - Check `DEBUG_BUY_FLAGS` shows all buy_* flags correctly
    - Check `DEBUG_STRATEGY_FINAL` shows correct decision based on flags
    - Verify canonical BUY rule: all flags True → decision=BUY

  - **Confirm:**
    - Signals and decisions are correct for several symbols (ALGO, LDO, TON, BTC, CRO, etc.)
    - ALERTS ON always triggers evaluation
    - **Alerts are emitted when business rules say BUY/SELL** (never blocked by risk)
    - **Risk only blocks order placement, not alerts**
    - Throttle entries appear when alerts are suppressed
    - Volume logic uses current_volume (hourly), not volume_24h
    - RSI thresholds match strategy config
    - MA checks use correct tolerances
    - Alert enabled flags are checked correctly

- **If something is wrong in AWS:**
  - Fix the code
  - Rebuild and redeploy the backend
  - **Re-run the audit until everything is correct**
  - **Iterate until 100% correct**

### 7. Watchlist & Alerts End-to-End Check

- Coordinate with the frontend workflow if needed, but from the backend side:
  - Verify that watchlist state (`alert_enabled`, `trade_enabled`, presets) is consistent in the DB.
  - Confirm that canonical selector (`get_canonical_watchlist_item` / `select_preferred_watchlist_item`) is used consistently.
  - Check that toggling Trading/Alerts in the UI is reflected in the DB row that SignalMonitor actually reads.

### 8. Safety: No Real Orders

- **NEVER create real orders:**
  - When simulating orders, always:
    - Use test/dry-run paths if present
    - Or short-circuit the actual exchange API call
    - Keep `trade_enabled = False` for test symbols
  - Ensure you NEVER hit live trading APIs with real side/quantity on behalf of the user
  - **Always send alerts if conditions are met** (alerts are independent of orders)

### 9. Automatic Remediation & Iteration

- **Patch backend code when mismatches are found:**
  - If any discrepancy is found between:
    - business rules (canonical documents)
    - backend decisions
    - logs
    - Monitoring → Telegram Messages
  - You MUST:
    - Fix the root cause in the backend
    - Ensure code matches canonical business rules
    - Add or update tests to cover the case
    - Redeploy to AWS
    - **Validate live telemetry** (check logs, endpoints, alerts)
    - Re-run the checks
    - **Repeat until all issues are resolved**
    - **Iterate until 100% correct**

### 10. Final Report

- At the end of the workflow, produce a concise but complete report:
  - What was requested.
  - Which modules and endpoints are involved.
  - What was wrong (root causes).
  - What code changes were made (high-level).
  - Which tests were added/updated.
  - How deployment was performed.
  - What was validated in AWS (endpoints + log snippets).
  - Explicit confirmation that:
    - Alerts follow the canonical business rules.
    - No real orders were sent.
    - Backend and business rules are aligned.

**This backend audit workflow MUST always run the full cycle: analyze → fix → test → deploy → audit on AWS → iterate → final confirmation.**

---

## Quick Reference Commands

### Local Testing
```bash
cd /Users/carloscruz/automated-trading-platform/backend
pytest -q
pytest tests/test_trading_signals.py -v  # Example targeted test
```

### Local Backend Run
```bash
cd /Users/carloscruz/automated-trading-platform
docker compose up backend -d
# Or: python -m uvicorn app.main:app --reload
```

### Local API Tests
```bash
curl http://localhost:8000/api/watchlist
curl http://localhost:8000/api/signals?exchange=CRYPTO_COM&symbol=ALGO_USDT
curl http://localhost:8000/api/monitoring/telegram-messages
```

### AWS Deployment
```bash
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose pull'"
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose up --build -d'"
```

### AWS Health Check
```bash
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose ps'"
curl -s https://monitoring-ai-dashboard-nu.vercel.app/api/health
```

### AWS Backend Logs
```bash
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker logs automated-trading-platform-backend-aws-1 --tail 500 | grep -E 'DEBUG_STRATEGY_FINAL|DEBUG_BUY_FLAGS|DEBUG_RESOLVED_PROFILE|STRATEGY_DEBUG_MARKER'"
```

### AWS API Tests
```bash
curl -s https://monitoring-ai-dashboard-nu.vercel.app/api/watchlist | jq '.coins[0].strategy'
curl -s "https://monitoring-ai-dashboard-nu.vercel.app/api/signals?exchange=CRYPTO_COM&symbol=ALGO_USDT" | jq '.strategy.decision'
```

---

## Key Backend Modules

### Core Signal Logic
- `backend/app/services/trading_signals.py` - Canonical BUY/SELL signal calculation
- `backend/app/services/strategy_profiles.py` - Preset resolution and strategy config
- `backend/app/services/signal_monitor.py` - Signal monitoring and alert emission

### Monitoring Services
- `backend/app/services/buy_index_monitor.py` - BTC index monitoring
- `backend/app/api/routes_monitoring.py` - Monitoring endpoints

### Watchlist & Market
- `backend/app/services/watchlist_selector.py` - Canonical watchlist item selection
- `backend/app/api/routes_market.py` - Market data and watchlist endpoints
- `backend/app/api/routes_dashboard.py` - Dashboard state endpoints

### Risk & Orders
- `backend/app/services/order_position_service.py` - Portfolio risk calculation
- `backend/app/services/signal_throttle.py` - Alert throttling logic

---

## Validation Checklist

For every backend change, validate:

- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Local API endpoints return correct data
- [ ] Strategy decisions match canonical rules
- [ ] Buy/sell signals are consistent with flags
- [ ] Alerts are emitted when conditions are met
- [ ] Risk blocks orders, not alerts
- [ ] Throttling works correctly
- [ ] Watchlist state is consistent in DB
- [ ] Canonical selector is used everywhere
- [ ] AWS deployment successful
- [ ] AWS logs show correct behavior
- [ ] No real orders were created
- [ ] Business rules are followed

---

## Related Workflows

- **Watchlist Audit:** `docs/WORKFLOW_WATCHLIST_AUDIT.md` - Full Watchlist validation workflow
- **Frontend Change:** `docs/WORKFLOW_FRONTEND_CHANGE_VALIDATED.md` - Frontend validation workflow
- **Autonomous Execution Guidelines:** `docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md` - General execution protocol

---

## Notes

- This workflow is designed for backend changes that affect strategy, alerts, or watchlist behavior
- Always test locally before deploying to AWS
- Never create real orders during testing
- Always validate against business rules before marking as complete
- Use canonical selectors consistently across all endpoints

