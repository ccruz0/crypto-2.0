# Auto ML entry model — operator runbook

**Scope:** Auto preset only. Swing / scalp / intraday unchanged.  
**ADRs:** ADR-0004 in `docs/project-history/architecture_decisions.md`.

## What it does

1. Rule engine finds a BUY candidate (same as today).
2. If coin preset is `auto` and `AUTO_ML_ENABLED=true`, a sklearn model scores the entry.
3. Score &lt; `AUTO_ML_THRESHOLD` → WAIT (no alert/order from that BUY).
4. Retrain/promote is offline via `scripts/retrain_and_promote_auto_entry.py`.

## Env flags

| Variable | Compose default (backend-aws) | Effect |
|----------|-------------------------------|--------|
| `AUTO_ML_ENABLED` | **true** | Live BUY gate |
| `AUTO_ML_THRESHOLD` | 0.5 | Min P(good) |
| `AUTO_ML_MODEL_PATH` | `/data/auto_ml/current.joblib` | Artifact (host `./models/auto_entry`) |
| `AUTO_ML_SHADOW_LOG` | true | Log `[AUTO_ML]` scores without blocking |
| `AUTO_ML_AUTONOMOUS_PROMOTE` | **true** | Allow promote of `current.joblib` |
| `AUTO_ML_PROMOTE_MIN_ROWS` | 20 | Min labels to promote |
| `AUTO_ML_PROMOTE_MIN_DELTA` | 0.0 | Min metric gain vs current |

Override any flag via `.env.aws` or shell export before `compose up`.

## Enable / apply on AWS host (operator)

```bash
cd /home/ubuntu/crypto-2.0   # or your deploy path
git pull

# Seed a model into the mounted dir (fail-open until this exists)
mkdir -p models/auto_entry
backend/.venv/bin/python -m pip install -r scripts/requirements-auto-ml.txt
AUTO_ML_AUTONOMOUS_PROMOTE=true backend/.venv/bin/python \
  scripts/retrain_and_promote_auto_entry.py \
  --api-url https://dashboard.hilovivo.com --days 30 \
  --out-dir models/auto_entry --no-telegram
# If too few labels, use --demo --min-rows 4 --promote-min-rows 4 --allow-single-class --force-promote once.

# Recreate backend so env + volume take effect (no full stack rebuild required)
docker compose --profile aws up -d backend-aws --force-recreate

# Verify
curl -sS http://127.0.0.1:8002/api/config/auto-ml | jq '{gate_enabled,autonomous_promote,model_present,version}'
docker compose --profile aws logs --tail=50 backend-aws | grep AUTO_ML || true
```

## Offline train / promote

```bash
backend/.venv/bin/python -m pip install -r scripts/requirements-auto-ml.txt

# Demo
AUTO_ML_AUTONOMOUS_PROMOTE=true backend/.venv/bin/python \
  scripts/retrain_and_promote_auto_entry.py --demo \
  --min-rows 4 --promote-min-rows 4 --allow-single-class

# From API (prod alerts)
AUTO_ML_AUTONOMOUS_PROMOTE=true backend/.venv/bin/python \
  scripts/retrain_and_promote_auto_entry.py \
  --api-url https://dashboard.hilovivo.com --days 30
```

Dry-run: add `--dry-run`. Force: `--force-promote`.

## Status API

`GET /api/config/auto-ml` — gate flags, model version, promote timestamps, holdout metrics.  
Strategy Config UI shows the same when preset = Auto.

## Rollback

1. Set `AUTO_ML_ENABLED=false` in `.env.aws` (or compose) and recreate `backend-aws`.
2. Or replace `models/auto_entry/current.joblib` with a previous `auto_entry_vN.joblib`.
3. Do **not** flip Jarvis ACW `patch_apply` / GitHub write for this path.

## Production notes

- Host is memory-constrained; keep sklearn offline train off the hot path when possible (cron / LAB).
- Fail-open: missing model → allow rule BUY + log warning.
- Never commit `.joblib` binaries (gitignored under `models/auto_entry/`).
