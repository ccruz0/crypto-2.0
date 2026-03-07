# Mandate #1: Trading Platform Repair Audit (Read-only)

Pegar este texto en la UI de OpenClaw para ejecutar el primer mandato formal.

---

## Goal

- Produce a prioritized fix plan for Hilovivo trading platform stability and safety.

## Scope

- **Repository:** automated-trading-platform
- **Focus areas:**
  - Order lifecycle: creation, SL/TP placement, updates, cancels, sold logic
  - Kill switch / global safety controls
  - Watchlist state consistency (dedupe, toggles, persistence)
  - Telegram command handling and deduplication
  - Scheduler and monitoring services interactions
- Nginx/OpenClaw embedding does not matter for this mandate.

## Rules

- **Read-only only.** Do not modify files. Do not run destructive commands.
- Do not print or request secrets.
- If you need runtime data, ask for the exact command and why.

## Deliverable format

1. **System map** (key modules and data flows)
2. **Top 10 failure modes** (with file paths + functions + why)
3. **Repro steps** for each (best-effort from code)
4. **Fix plan:**
   - **Phase 0:** safety guards (kill switch, idempotency, race conditions)
   - **Phase 1:** correctness (orders, SL/TP, state)
   - **Phase 2:** observability (logs/metrics, alerts, dashboards)
5. **"First PR" suggestion:** the smallest safe change that removes the biggest risk

## Start by scanning these paths

- `backend/app/services`
- `backend/app/api`
- `backend/app/models`
- `scripts/`
- `docker-compose*` and `nginx/` only if they influence runtime behavior

---

*Mandate #2 can be oriented to "first PR" (with edit permission) and clear acceptance criteria.*
