# Auto ML entry model — operator runbook

**Scope:** Auto preset only. Swing / scalp / intraday unchanged.  
**ADRs:** ADR-0004 in `docs/project-history/architecture_decisions.md`.

## What it does

1. Rule engine finds a BUY candidate (same as today).
2. If coin preset is `auto` and `AUTO_ML_ENABLED=true`, a sklearn model scores the entry.
3. Score &lt; `AUTO_ML_THRESHOLD` → WAIT (no alert/order from that BUY).
4. Retrain/promote is offline via `scripts/retrain_and_promote_auto_entry.py`.

## Env flags

| Variable | Default | Effect |
|----------|---------|--------|
| `AUTO_ML_ENABLED` | **true** (compose) | Live BUY gate |
| `AUTO_ML_THRESHOLD` | 0.5 | Min P(good) |
| `AUTO_ML_MODEL_PATH` | `/data/auto_ml/current.joblib` | Artifact (host `./models/auto_entry`) |
| `AUTO_ML_SHADOW_LOG` | true | Log `[AUTO_ML]` scores without blocking |
| `AUTO_ML_AUTONOMOUS_PROMOTE` | **false** | Cron/autonomous promote of `current.joblib` (leave off) |
| `AUTO_ML_HUMAN_PROMOTE` | **false** (backend reads process env) | Shell/workflow merit promote; **not** required for dashboard/API promote |
| `AUTO_ML_PROMOTE_MIN_ROWS` | 20 | Min labels to promote |
| `AUTO_ML_PROMOTE_MIN_DELTA` | 0.0 | Min metric gain vs current |

`AUTO_ML_HUMAN_PROMOTE` is **not** wired in `docker-compose.yml` (path-guard).
Override only via process env on retrain shells, GitHub `workflow_dispatch`
(`dry_run_only=false`), or use the dashboard/API promote path below (no env flip).

## Enable / apply on AWS host (operator)

```bash
cd /home/ubuntu/crypto-2.0   # or your deploy path
git pull

# Seed a model into the mounted dir (fail-open until this exists)
mkdir -p models/auto_entry
backend/.venv/bin/python -m pip install -r scripts/requirements-auto-ml.txt
AUTO_ML_HUMAN_PROMOTE=true AUTO_ML_AUTONOMOUS_PROMOTE=false backend/.venv/bin/python \
  scripts/retrain_and_promote_auto_entry.py \
  --api-url https://dashboard.hilovivo.com --days 30 \
  --out-dir models/auto_entry --no-telegram
# If too few labels, use --demo --min-rows 4 --promote-min-rows 4 --allow-single-class --force-promote once.

# Recreate backend so env + volume take effect (no full stack rebuild required)
docker compose --profile aws up -d backend-aws --force-recreate

# Verify
curl -sS http://127.0.0.1:8002/api/config/auto-ml | jq '{gate_enabled,autonomous_promote,human_promote,model_present,version}'
docker compose --profile aws logs --tail=50 backend-aws | grep AUTO_ML || true
```

## Telegram on version update

Cada vez que se actualiza `current.joblib` (retrain promote o `train_auto_entry_model`
sin `--no-promote`), se envía un mensaje a Telegram con:

- versión anterior → nueva
- **por qué** (métrica mejoró, primera versión, force, etc.)
- **cambios aplicados** (métricas, dataset source/rows, gate)

Requiere `TELEGRAM_BOT_TOKEN_AWS` / `TELEGRAM_CHAT_ID_AWS` (o genéricos) en el entorno
del proceso que corre el retrain. Usa `--no-telegram` para silenciar.

## Offline train / promote

```bash
backend/.venv/bin/python -m pip install -r scripts/requirements-auto-ml.txt

# Demo
AUTO_ML_HUMAN_PROMOTE=true AUTO_ML_AUTONOMOUS_PROMOTE=false backend/.venv/bin/python \
  scripts/retrain_and_promote_auto_entry.py --demo \
  --min-rows 4 --promote-min-rows 4 --allow-single-class

# From API (prod alerts)
AUTO_ML_HUMAN_PROMOTE=true AUTO_ML_AUTONOMOUS_PROMOTE=false backend/.venv/bin/python \
  scripts/retrain_and_promote_auto_entry.py \
  --api-url https://dashboard.hilovivo.com --days 30
```

Dry-run: add `--dry-run`. Force: `--force-promote`.

## Status API

`GET /api/config/auto-ml` — gate flags, model version, promote timestamps, holdout metrics,
pending candidate (`pending_promote`, long/short fill counts).  
Strategy Config UI shows the same when preset = Auto.

## Human promote (dashboard / API — no compose change)

Weekly hybrid retrain writes `/data/auto_ml/pending_promote.json` when the **quality
gate** passes (merit-only; cron still blocks silent promote).

**Preferred operator path (no `AUTO_ML_HUMAN_PROMOTE` env required):**

1. Open Strategy Configuration → preset **Auto** → review pending candidate banner.
2. Click **Promote candidate (human gate)**, or:

```bash
curl -sS -X POST https://dashboard.hilovivo.com/api/config/auto-ml/promote \
  -H 'Content-Type: application/json' \
  -d '{"confirm": true, "telegram": true}'
```

The API runs the merit check on `candidate.joblib` and copies to `current.joblib`
with `human_promote=true` in the manifest. It does **not** rewrite `strategy_rules.auto`
and never sets `AUTO_ML_AUTONOMOUS_PROMOTE=true`.

**Alternative:** GitHub Actions **Ops — Auto ML hybrid retrain** with
`dry_run_only=false` (sets `AUTO_ML_HUMAN_PROMOTE=true` in the remote shell only).

**Alternative:** one-off shell retrain with `AUTO_ML_HUMAN_PROMOTE=true` exported for
that process (see Offline train / promote above).

## Rollback

1. Set `AUTO_ML_ENABLED=false` in `.env.aws` (or compose) and recreate `backend-aws`.
2. Or replace `models/auto_entry/current.joblib` with a previous `auto_entry_vN.joblib`.
3. Do **not** flip Jarvis ACW `patch_apply` / GitHub write for this path.

## Production notes

- Host is memory-constrained; keep sklearn offline train off the hot path when possible (cron / LAB).
- Fail-open: missing model → allow rule BUY + log warning.
- Never commit `.joblib` binaries (gitignored under `models/auto_entry/`).

---

## Phase 0 — Honest retrain from prod alerts (no force)

**Goal:** Replace / challenge the force-promoted demo model with a merit promote
from **real prod alerts**. Labels are still **alert-path** (OHLCV forward:
`dir_acc_1h OR tp_before_sl`) until Phase 1 wires `trade_outcomes`.

**Do not use `--force-promote`.** Do not deploy from this section; ops only.

### Success / fail criteria

| Gate | Pass | Fail |
|------|------|------|
| Labeled fit rows | `n_fit_rows ≥ 20` (`AUTO_ML_PROMOTE_MIN_ROWS`) | Below floor → no promote |
| Holdout metric | Candidate primary metric ≥ current + `AUTO_ML_PROMOTE_MIN_DELTA` (default 0) | Flat/worse → leave current |
| Class balance | Holdout usable (not single-class) | `single_class_or_no_holdout` |
| Flag | `AUTO_ML_HUMAN_PROMOTE=true` for shell/workflow merit path, **or** POST `/api/config/auto-ml/promote` / dashboard button (no env) | Disabled shell path → `autonomous_promote_disabled`; API promote still works when pending |
| Autonomous | `AUTO_ML_AUTONOMOUS_PROMOTE` stays **false** in prod | Never enable for cron |

Primary metric: holdout `roc_auc`, else `accuracy` (see `auto_entry_promote.primary_metric`).

### 1) Inspect dataset size first (read-only)

On the AWS host (or any machine that can reach the dashboard API):

```bash
cd /home/ubuntu/crypto-2.0   # or your deploy path

backend/.venv/bin/python -m pip install -r scripts/requirements-auto-ml.txt

backend/.venv/bin/python scripts/build_auto_ml_dataset.py \
  --api-url https://dashboard.hilovivo.com --days 30 \
  --out docs/analysis/auto-ml-dataset-prod.json
```

Inspect before training (never print secrets):

```bash
python3 - <<'PY'
import json
from pathlib import Path
d = json.loads(Path("docs/analysis/auto-ml-dataset-prod.json").read_text())
meta = d.get("meta") or {}
rows = d.get("rows") or []
print({
    "source": meta.get("source"),
    "n_dataset_rows": meta.get("n_dataset_rows", len(rows)),
    "n_positive": meta.get("n_positive"),
    "n_negative": meta.get("n_negative"),
    "label_def": meta.get("label_def"),
})
PY
```

- If **n &lt; 20**: stop. Do **not** train+promote. Either widen `--days`, leave the live
  model as-is, or set `AUTO_ML_ENABLED=false` / rely on shadow-only until enough labels
  (operator choice; prefer no force).
- If **n ≥ 20**: continue.

### 2) Retrain without `--force-promote`

```bash
AUTO_ML_HUMAN_PROMOTE=true AUTO_ML_AUTONOMOUS_PROMOTE=false backend/.venv/bin/python \
  scripts/retrain_and_promote_auto_entry.py \
  --api-url https://dashboard.hilovivo.com --days 30 \
  --out-dir models/auto_entry
# Optional first pass: add --dry-run to print the decision without writing current.joblib
```

Expect JSON on stdout with `decision.should_promote` and `decision.reason`.

### 3) If `should_promote` is false

| `decision.reason` (typical) | Action |
|-----------------------------|--------|
| `n_fit_rows=…<20` | Collect more labeled alerts; do not force |
| `metric_not_improved:…` | Keep current `current.joblib`; candidate stays in `candidate.joblib` for inspection |
| `single_class_or_no_holdout` | Dataset not usable for promote; fix class balance / window |
| `autonomous_promote_disabled` | Promote via dashboard/API (`POST /api/config/auto-ml/promote`), `workflow_dispatch dry_run_only=false`, or export `AUTO_ML_HUMAN_PROMOTE=true` for shell retrain — still no `--force-promote` |

**Do not** add `--force-promote` to “make it green.” If the live model is still the
old force-demo and merit cannot pass, prefer gate off or shadow-only until Phase 1
trade labels are ready:

```bash
# Optional: disable live BUY block (compose/env), then recreate backend-aws
# AUTO_ML_ENABLED=false
```

### 4) Verify

```bash
curl -sS https://dashboard.hilovivo.com/api/config/auto-ml | jq \
  '{gate_enabled, autonomous_promote, human_promote, model_present, version, n_fit_rows, promote_reason, metrics, promoted_at}'

# On host loopback if preferred:
curl -sS http://127.0.0.1:8002/api/config/auto-ml | jq \
  '{gate_enabled, autonomous_promote, model_present, version, n_fit_rows, promote_reason, metrics}'
```

**Pass:** `promote_reason` is merit-style (e.g. contains `metric_improved` / first promote),
`n_fit_rows ≥ 20`, metrics better than coin-flip baseline when a prior model exists.  
**Fail / no-op:** `promoted: false` in retrain JSON and API still shows prior version /
`promote_reason: force` from the old seed — that is OK; leave it until data improves.

### Label provenance

| Mode | Flag | Labels |
|------|------|--------|
| Phase 0 | `--label-source alert` (default) | OHLCV forward: `dir_acc_1h OR tp_before_sl` |
| Phase 1b fills | `--label-source trade_outcomes` | COMPLETE `trade_outcomes`: `y=1 if pnl_usd > 0` (long **and** short round-trips; short closes via BUY cover legs) |
| Phase 1b hybrid | `--label-source hybrid` | Prefer fill PnL when alert has a COMPLETE outcome; else alert-path |

Short realized P&L: `build_trade_outcomes.py` supplements intent-path rows from canonical
BUY short-close covers (`_short_close_buy_filter` shape) when the SELL entry join missed
the exit child — same anti-guess rules as the sales report (#614).

Phase 1a still builds rows via `scripts/build_trade_outcomes.py`. Phase 1b only
changes the **training dataset** — live BUY gate / promote merit rules unchanged.

### Phase 1b — train on executed TP/SL (hybrid recommended)

Requires DB with populated `trade_outcomes` (run Phase 1a builder first if empty).

```bash
# 1) Refresh COMPLETE outcomes from exchange joins (if needed)
# On prod, /repo is read-only — write coverage to /tmp and pass --write-db.
backend/.venv/bin/python scripts/build_trade_outcomes.py \
  --database-url "$DATABASE_URL" --days 90 \
  --write-db --out /tmp/trade-outcomes-coverage.json

# 2) Dataset: prefer realized fills, keep alert labels for open/unmatched
backend/.venv/bin/python scripts/build_auto_ml_dataset.py \
  --database-url "$DATABASE_URL" --days 90 \
  --label-source hybrid \
  --out docs/analysis/auto-ml-dataset-hybrid.json

# Inspect counts (no secrets)
python3 - <<'PY'
import json
from pathlib import Path
m = json.loads(Path("docs/analysis/auto-ml-dataset-hybrid.json").read_text())["meta"]
print({k: m.get(k) for k in (
    "label_source", "phase", "n_dataset_rows", "n_from_trade_outcome",
    "n_from_alert", "n_positive", "n_negative", "label_def",
)})
PY

# 3) Retrain + merit promote (no --force-promote; human gate only)
AUTO_ML_HUMAN_PROMOTE=true AUTO_ML_AUTONOMOUS_PROMOTE=false backend/.venv/bin/python \
  scripts/retrain_and_promote_auto_entry.py \
  --database-url "$DATABASE_URL" --days 90 \
  --label-source hybrid \
  --out-dir models/auto_entry
```

If `n_from_trade_outcome` is low, widen `--days` or keep hybrid (alert fallback).
Do **not** `--force-promote` to paper over thin fill labels.

### Ops — scheduled / dispatch hybrid retrain

GitHub Actions workflow **Ops — Auto ML hybrid retrain**:

| Trigger | Promote? | Notes |
|---------|----------|--------|
| `schedule` (Mon 05:00 UTC) | **No** — dry-run only | Trains candidate, prints `DATASET_META` + `AUTO_ML_*_HEARTBEAT` progress |
| `workflow_dispatch` `dry_run_only=true` | No | Same as cron |
| `workflow_dispatch` `dry_run_only=false` | Human merit gate only | Sets `AUTO_ML_HUMAN_PROMOTE=true`; promotes if holdout metric improves; never `--force-promote` or `AUTO_ML_AUTONOMOUS_PROMOTE=true` |

**Related ops jobs (do not duplicate work):**

- **Ops — trade_outcomes diario** (daily 04:30 UTC) rebuilds `trade_outcomes` only.
- Hybrid retrain passes `--skip-if-fresh-hours 26` to `build_trade_outcomes.py` so Monday
  runs skip the heavy rebuild when the daily job already refreshed the table (30 min earlier).
- SSM remote timeout is **3600s** with CI poll up to ~3700s; last `AUTO_ML_DATASET_HEARTBEAT`
  or `AUTO_ML_RETRAIN_HEARTBEAT` line in workflow stdout shows where a hang occurred.
- **Concurrency:** workflow uses GitHub Actions group `auto-ml-hybrid-retrain-prod` with
  `cancel-in-progress: false`. A second dispatch (cron + manual, or two manual runs) **queues**
  until the in-flight SSM retrain finishes — do not rely on parallel runs on the prod host.

Also useful: **Ops — Auto ML fill feature diag** (read-only fill/context diagnostics).

---

## Phase 2 — Learn SL/TP from fills (#623)

**Goal:** Offline walk-forward grid search on COMPLETE `trade_outcomes` (long **and** short)
to propose SL/TP %% distances vs conservative 3%/3% baseline. Human promote only;
live gate **default OFF**. Does **not** amend open positions or enable invent-heal.

### Env flags

| Variable | Default | Effect |
|----------|---------|--------|
| `AUTO_ML_SLTP_ENABLED` | **false** | Use promoted `sltp_manifest.json` for Auto-preset **new** fill protection |
| `AUTO_ML_SLTP_SHADOW_LOG` | true | Log `[AUTO_ML_SLTP]` learned vs watchlist when gate off |
| `AUTO_ML_SLTP_AUTONOMOUS_PROMOTE` | **false** | Never enable in prod |
| `AUTO_ML_SLTP_HUMAN_PROMOTE` | **false** | Shell/workflow merit promote of SL/TP manifest |
| `AUTO_ML_SLTP_DIR` | same as entry model dir | `sltp_manifest.json` location |
| `AUTO_ML_SLTP_PROMOTE_MIN_ROWS` | 20 | Min COMPLETE outcomes to promote |
| `AUTO_ML_SLTP_PROMOTE_MIN_DELTA` | 0.0 | Min holdout expectancy gain vs baseline |

BUY entry gate (`AUTO_ML_ENABLED`) is unchanged by Phase 2.

### Offline retrain

```bash
backend/.venv/bin/python -m pip install -r scripts/requirements-auto-ml.txt

# Demo (24 synthetic fills)
backend/.venv/bin/python scripts/retrain_and_promote_auto_sltp.py --demo --min-rows 20

# Prod DB (merit report only; writes pending when quality passes)
backend/.venv/bin/python scripts/retrain_and_promote_auto_sltp.py \
  --database-url "$DATABASE_URL" --days 90 --dry-run

# Human promote via shell (optional)
AUTO_ML_SLTP_HUMAN_PROMOTE=true backend/.venv/bin/python \
  scripts/retrain_and_promote_auto_sltp.py --database-url "$DATABASE_URL" --days 90
```

Merit report: `models/auto_entry/sltp_merit_report_vN.txt` (expectancy, win rate, max DD vs baseline).

### Human promote (dashboard / API)

```bash
curl -sS https://dashboard.hilovivo.com/api/config/auto-ml/sltp | jq \
  '{gate_enabled, manifest_present, sl_pct, tp_pct, pending_promote, metrics}'

curl -sS -X POST https://dashboard.hilovivo.com/api/config/auto-ml/sltp/promote \
  -H 'Content-Type: application/json' -d '{"confirm": true}'
```

Strategy Config → Auto also shows **Auto ML SL/TP (Phase 2)** panel with promote button.

### Enable live gate (operator, after promote)

```bash
# .env.aws — explicit opt-in only
AUTO_ML_SLTP_ENABLED=true
docker compose --profile aws up -d backend-aws --force-recreate
```

### Rollback

1. Set `AUTO_ML_SLTP_ENABLED=false` and recreate backend.
2. Or restore previous `sltp_manifest.json` from `sltp_manifest.prev.json`.
3. Open positions are **not** retrofitted.

### Tests

```bash
cd backend && python -m pytest \
  tests/test_auto_sltp_offline.py \
  tests/test_auto_sltp_promote.py \
  tests/test_auto_sltp_live_gate.py \
  tests/test_auto_sltp_status_api.py -q
```
