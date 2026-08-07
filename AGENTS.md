# AGENTS.md

Operational guidance for AI coding agents working in this repository. See
`CLAUDE.md` for the project's hard guardrails (production is human-gated,
read-only by default). This file adds environment/run guidance.

## Cursor Cloud specific instructions

The Cursor Cloud dev environment runs the ATP stack **natively on the VM**
(not via Docker — Docker is not installed and Docker-in-Docker is unreliable in
this VM). The dependency-refresh update script installs Python/Node deps; the
system packages (PostgreSQL 16, Python 3.11 from deadsnakes), the
`/workspace/.venv` virtualenv, the local Postgres cluster + data, and the
gitignored `.env` files are all captured in the VM snapshot.

### Services and how to run them (dev mode)
- **PostgreSQL 16** (system service, port 5432, db `atp`, role `trader`/`traderpass`).
  It does not auto-start on boot here — start it with:
  `sudo pg_ctlcluster 16 main start`
- **Backend** — FastAPI, port `8002`. Run from the repo root with the venv +
  `.env` loaded, using `--app-dir backend` so `Settings` reads `/workspace/.env`:
  `. .venv/bin/activate && set -a && . ./.env && set +a`
  then `python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8002`.
  Health: `curl http://localhost:8002/api/health`; API docs: `/docs`.
- **Frontend** — Next.js 16 dev server, port `3000`: `cd frontend && npm run dev`
  (reads `frontend/.env.local`; proxies `/health`, `/dashboard`, `/market`,
  `/orders`, `/signals` to the backend).
- **Market updater** (optional) — `cd backend && python3 run_updater.py`
  (with the venv + `.env` loaded). Populates live prices/indicators.

### Non-obvious gotchas (important)
- **Backend must run detached from a controlling TTY.** At import time the app
  calls a Telegram-token `getpass` prompt; with a real TTY (e.g. a plain tmux
  pane) it blocks startup forever. Run it with no controlling terminal and stdin
  from /dev/null, e.g. wrap the command in `setsid bash -c '…' </dev/null`.
  In Docker/CI there is no TTY so it returns immediately — the native runner
  must replicate that.
- **Fresh/empty DB breaks `Base.metadata.create_all`.** Two models declare a
  duplicate index name (`ix_order_intents_signal_id` in
  `backend/app/models/order_intent.py` and `ix_trade_outcomes_symbol` in
  `backend/app/models/trade_outcome.py` — each defined both via `index=True` and
  an explicit `Index(...)`). On an empty database `create_all` aborts the whole
  transaction, so many core tables are never created. The tables in this VM were
  already bootstrapped (created one-per-transaction) and persist in the snapshot,
  so normal startups are clean. If you ever recreate the DB from scratch, create
  tables per-table in their own transactions (skip/dedupe the duplicate index)
  rather than a single `create_all`. The same bug makes a few tests that call
  `create_all` against SQLite fail (e.g. `tests/test_order_intent_live_trading_status.py`).
- **Binance is geo-blocked from this VM (HTTP 451).** The market updater falls
  back to Crypto.com public tickers (which work), but only ~25 candles are
  available, so MA50/EMA10-based signals stay empty. As a result the
  **Watchlist / Portfolio dashboard tabs show "Cannot read properties of null
  (reading 'toFixed')"** (a frontend null-handling issue triggered by missing
  signals), while the header, System Health, **Settings**, and **Configure
  Strategy** modals work normally. This is an environment/network limitation, not
  a setup failure.
- **Live trading / Telegram are disabled locally** via `.env` (`LIVE_TRADING=false`,
  `TRADING_ENABLED=false`, `RUN_TELEGRAM=false`, `USE_CRYPTO_PROXY=false`). Keep
  them off in local dev (see `CLAUDE.md` / `DEV.md`).
- The local `.env` sets `DATABASE_URL=postgresql://trader:traderpass@localhost:5432/atp`
  (the repo's example uses host `db`, which only resolves inside Docker). `.env`,
  `.env.local`, `frontend/.env.local`, and `.venv/` are gitignored.

### Lint / test / build (dev)
- Backend lint: `. .venv/bin/activate && ruff check backend/app`
  (the repo has no ruff config, so default rules report many pre-existing findings).
- Backend tests: `cd backend && python -m pytest tests/` (3200+ tests; some
  require network/exchange access — run targeted files for quick checks).
- Frontend lint: `cd frontend && npm run lint` (pre-existing findings exist).
- Frontend unit tests: `cd frontend && npm run test` (Vitest).
- Frontend build: `cd frontend && npm run build`.
- Pre-commit hooks (`.pre-commit-config.yaml`) use black/ruff/prettier/eslint and
  `scripts/pre_commit_checks.sh`.

### Dashboard tabs (URL)
The main dashboard keeps `activeTab` in sync with `?tab=` (e.g. `/?tab=watchlist`,
`/?tab=monitoring`). Prefer deep-links or `data-testid="dashboard-tab-<id>"` /
`data-tab="<id>"` over brittle text clicks when automating. Unknown `tab` values
fall back to Portfolio. Version History is `?tab=version-history` (also the
header `v{version}` badge).

### Dashboard version history (mandatory on shippable PRs)
Every user-visible / production-bound change **must** append a new entry to
`VERSION_HISTORY` in `frontend/src/app/page.tsx` before the PR is considered
complete:

1. Bump the patch/minor version (e.g. `0.47` → `0.48`).
2. Set `date` (UTC/ISO day), a one-line `change`, and `details` covering:
   what shipped, why, PR numbers, and any operator-facing notes.
3. The header shows `v{latest}` and links to the Version History tab
   (newest-first). That tab is the in-dashboard changelog.

Do **not** ship a fix/feature PR without this entry. Pure docs/chore-only PRs
that never reach the running dashboard may skip it.
