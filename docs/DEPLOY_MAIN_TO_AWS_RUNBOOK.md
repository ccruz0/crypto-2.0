# Deploy main to AWS — Runbook and Evidence

Use this after merging `fix/local-dev-telegram-bootstrap` into `main`. AWS DB already has the singular table `watchlist_signal_state`. **Do NOT** apply `backend/migrations/20260128_create_watchlist_signal_states.sql` on AWS.

---

## Section A: Commands executed + outputs

### A.1 Git state (local or CI)

```bash
cd /path/to/automated-trading-platform
git branch --show-current
git log main -3 --oneline
git status -sb
```

**Example (confirm merge present on main):**

```
main
54115d8 docs(ops): add pre-production checklist (signal lifecycle, Telegram, orders, health)
e0a19d1 fix: align WatchlistSignalState with AWS DB schema + audit remediation
34c984e Use guardrail SKIP_REASON in test_api_key.py
## main...origin/main [ahead N]
```

- `main` must be the current branch.
- Latest commit on `main` should include the merge (e.g. pre-prod checklist or WatchlistSignalState fix).
- For a clean deploy: commit any runbook/verify changes, push `main`, then on AWS run the steps below.

### A.2 On AWS host — deploy and smoke

**1. Git (on AWS host)**

```bash
cd /home/ubuntu/automated-trading-platform
git fetch origin main
git checkout main
git pull origin main
git log -1 --oneline
```

Paste output: `_________________________`

**2. Deploy (do NOT run any migration that creates `watchlist_signal_states`)**

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/aws_up_backend.sh
```

Paste key lines (runtime.env presence, health):  
`_________________________`

**3. Smoke / evidence**

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/verify_backend_runtime.sh
```

Paste key sections:

- ENV CHECK (ENVIRONMENT, APP_ENV, RUNTIME_ORIGIN, E2E_CORRELATION_ID_SET):  
  `_________________________`
- RUNTIME ENV VALUES:  
  `_________________________`
- HEALTH:  
  `_________________________`
- DB watchlist_signal_state (row_count, latest_updated_at):  
  `_________________________`
- EVALUATE SYMBOL response:  
  `_________________________`
- LOGS [SIGNAL_STATE] / [SLTP_VARIANTS]:  
  `_________________________`
- TELEGRAM LOGS (snippet):  
  `_________________________`

---

## Section B: What changed

- **backend/app/api/routes_admin.py**: Added `POST /api/admin/debug/evaluate-symbol` (admin-only, X-Admin-Key) to trigger one-symbol signal evaluation for smoke/E2E. No other refactors.
- **scripts/aws/verify_backend_runtime.sh**: Extended to report ENVIRONMENT/APP_ENV/RUNTIME_ORIGIN, E2E_CORRELATION_ID_SET, DB table `watchlist_signal_state` (row count, latest_updated_at), and [SIGNAL_STATE] / [SLTP_VARIANTS] log lines.
- **README-ops.md**: Added subsection “Deploy main to production (post-merge)” with git steps, migration guardrail, and verify command.

No migrations were added or run on AWS. No unrelated refactors.

---

## Section C: Evidence checklist (pass/fail)

| Check | Pass/Fail | Note |
|-------|-----------|------|
| Git: main is branch, merge commit present | | From A.1 |
| AWS: backend-aws and market-updater use ENVIRONMENT=aws, APP_ENV=aws, RUNTIME_ORIGIN=AWS | | From verify RUNTIME ENV VALUES |
| E2E_CORRELATION_ID not set in prod | | E2E_CORRELATION_ID_SET=no |
| Telegram from secrets (no local bootstrap) | | TELEGRAM_*_PRESENT=yes in container |
| GET /health returns ok | | From verify HEALTH |
| DB table watchlist_signal_state exists and is written to | | row_count, latest_updated_at from verify |
| Controlled evaluation: POST /api/admin/debug/evaluate-symbol returns ok | | From EVALUATE SYMBOL |
| Logs show [SIGNAL_STATE] upsert after evaluate-symbol | | From verify LOGS |
| Telegram send attempt/success in logs (if applicable) | | From TELEGRAM LOGS |
| [SLTP_VARIANTS] / jsonl only if order path ran | | Optional |

---

## Section D: Risks and what to monitor (next 2 hours)

- **Stale code on AWS**: Ensure `git pull origin main` was run and no old image is running (`docker compose --profile aws ps`, rebuild if needed).
- **Env drift**: If ENVIRONMENT/APP_ENV/RUNTIME_ORIGIN are not aws/AWS, alerts and orders may be blocked; fix in `secrets/runtime.env` or docker-compose and restart.
- **watchlist_signal_state**: Table must stay singular; do not run `20260128_create_watchlist_signal_states.sql` on AWS.
- **Telegram**: Watch for blocked sends (reason_code in DB or logs); confirm channel/token in secrets.
- **Orders**: If order creation is expected, watch [SLTP_VARIANTS] and `/tmp/sltp_variants_*.jsonl` for failures; guardrails should block bad SL/TP formats.

**Monitor:** Backend logs for [SIGNAL_STATE], [SLTP_VARIANTS], Telegram send/block, and any 5xx or auth errors. Re-run `scripts/aws/verify_backend_runtime.sh` after 30–60 minutes to confirm health and env again.

---

## Production go/no-go verdict

Fill after completing Section A.2 and Section C:

- **GO** if: Git state correct, deploy succeeded, health ok, env=aws/AWS, E2E_CORRELATION_ID unset, table exists and has recent rows, evaluate-symbol returns ok, [SIGNAL_STATE] in logs, Telegram path as expected.
- **NO-GO** if: Health failing, wrong env, table missing or wrong name, evaluate-symbol error, or critical Telegram/order failure without a known fix.

Verdict: ____________  Date: ____________
