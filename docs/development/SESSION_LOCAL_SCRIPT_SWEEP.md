# SessionLocal → `create_db_session()` sweep (scripts & ops)

## Rule

- **Scripts, diagnostics, tools, and one-off utilities** under `backend/scripts/`, `backend/tools/`, and top-level `backend/*.py` helpers should open the ORM with:

  ```python
  from app.database import create_db_session

  db = create_db_session()
  try:
      ...
  finally:
      db.close()
  ```

- **`create_db_session()`** (in `backend/app/database.py`) raises **`RuntimeError`** with an explicit message when `SessionLocal` is `None` (no engine / failed init). That avoids `'NoneType' object is not callable` from bare `SessionLocal()`.

- **Application runtime** (FastAPI `get_db()`, services, schedulers, signal monitor) continues to use **`SessionLocal`** and **`if SessionLocal is None`**, so APIs can degrade without crashing the process.

## What was changed (this pass)

| Area | Action |
|------|--------|
| `backend/scripts/**/*.py` | Replaced `from app.database import SessionLocal` + `SessionLocal()` with `create_db_session` where the app session factory was used. |
| `backend/tools/**/*.py` | Same. |
| Top-level `backend/*.py` utilities | Same (via the same sweep). |
| Scripts that checked `if SessionLocal is None` | Removed the check; use `try: create_db_session()` / `except RuntimeError` where a friendly message or exit code was needed. |
| `backend/scripts/update_portfolio_cache.py` | Fixed broken `from app.core.database import SessionLocal` → `from app.database import create_db_session`. |
| `backend/scripts/import_order_history.py` | Type hint `db: SessionLocal` → `db: Session` (`sqlalchemy.orm.Session`). |
| `backend/market_updater.py` | DB bootstrap `try` block: dropped unused `SessionLocal` import; call sites already use `create_db_session()`. |

Volume (approximate, via import of `create_db_session`): **~126** files under `backend/scripts/` and `backend/tools/`, plus **~14** top-level `backend/*.py` utilities (counts may shift slightly as scripts evolve).

## Former outliers (now standardized)

These previously used a **local** `create_engine` + `sessionmaker` (sometimes named `SessionLocal`), which duplicated `app.database` URL resolution and could point at a different DB than the running app. They now use **`create_db_session()`**:

| File | Notes |
|------|--------|
| `backend/scripts/trigger_manual_alert.py` | Dropped hardcoded default Postgres URL; uses same engine rules as the app. |
| `backend/scripts/monitor_alerts.py` | Same. |
| `backend/tools/count_orders.py` | Same; `sys.path` fixed to insert `backend/` (not repo root) so `app` imports reliably. |

## What stays intentionally different

| File / area | Pattern | Reason |
|-------------|---------|--------|
| `backend/app/**` (services, API, `main.py`, etc.) | `SessionLocal` / `get_db()` | Core runtime; optional DB and existing guards must stay. |
| `backend/tests/**` | Mix of `SessionLocal`, `TestingSessionLocal`, mocks | Test harness; follow-up if we want stricter consistency. |

## Classification reference (high level)

| Class | Use `create_db_session()` | Keep `SessionLocal` / `get_db` |
|-------|---------------------------|--------------------------------|
| CLI / script / cron / diag | Yes | — |
| FastAPI dependency & request handlers | — | `get_db()` |
| Long-running workers & monitors inside `app/` | — | `SessionLocal` with `None` checks |
| Script that must not import `app` at all (rare) | Optional local engine | Almost everything under `backend/scripts/` / `backend/tools/` should use `create_db_session()` instead |

## Representative classification (concise)

| File | Area | Classification | Action |
|------|------|----------------|--------|
| `backend/scripts/*.py` (majority) | `main()` / CLI entry | **Switch** | `create_db_session()` |
| `backend/tools/*.py` | tool `main` | **Switch** | `create_db_session()` |
| `backend/*.py` one-off checks | module-level or `main` | **Switch** | `create_db_session()` |
| `backend/scripts/trigger_manual_alert.py` | manual alert / trace | **Switch** | `create_db_session()` (was local engine) |
| `backend/scripts/monitor_alerts.py` | alert monitor loop | **Switch** | Same |
| `backend/tools/count_orders.py` | order stats | **Switch** | Same |
| `backend/app/services/signal_monitor.py` | monitor cycles | **Stay** | `SessionLocal` + `None` checks |
| `backend/app/database.py` | `get_db()` | **Stay** | Yields `None` when DB unavailable |
| `backend/app/main.py` | startup probes | **Stay** | Explicit `SessionLocal` checks |
| `backend/tests/*.py` | tests | **Follow-up** | `SessionLocal` / `TestingSessionLocal` / mocks |

## Verification

From repo root (with `backend` on `PYTHONPATH` and venv active):

```bash
cd backend && .venv/bin/python -c "from app.database import create_db_session; create_db_session().close()"
```

If the engine is missing, you should see a clear `RuntimeError`, not `NoneType` is not callable.

**Runtime smoke (narrow):** `create_db_session()` + `SELECT 1` should succeed whenever the engine exists. Scripts that query real tables (`count_orders`, `monitor_alerts`) exit **2** with a short message if the schema is missing (typical empty local SQLite) — that still confirms session wiring. Shared helper: **`app.database.exit_2_if_missing_schema_tables`**. `monitor_alerts.get_recent_alerts` uses a **bound UTC cutoff** instead of `NOW() - INTERVAL ':minutes minutes'` (invalid binding / not portable on SQLite).
