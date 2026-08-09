# Auto ML Entry Classifier — Built & Planned

**Product:** ATP / Jarvis (`ccruz0/crypto-2.0`)  
**Prod:** https://dashboard.hilovivo.com  
**Doc date:** 2026-08-09  
**Status:** Phase **1b hybrid live** (model **v12**) · further ML work on **observe**  

> Notion tip: Import this Markdown (**⋯ → Import → Markdown**), or paste into a new page. Tables and headings import cleanly.

---

## 1. One-page snapshot

| | |
|--|--|
| **Goal** | Filter Auto strategy BUY entries with an ML score; learn from **real TP/SL** when possible |
| **Live now** | Hybrid model **v12** · `label_source=hybrid` · **30** fill rows + **774** alert rows · AUC **~0.760** |
| **Gate** | On (`AUTO_ML_ENABLED`) · shadow log on · fail-open if model missing |
| **Promote rule** | Merit only (holdout metric must improve) · **never** `--force-promote` |
| **Ops cadence** | Weekly dry-run cron **Mon 05:00 UTC**; live promote = manual Actions dispatch |
| **Observe** | Watch gate + Monday cron; promote only when dry-run beats live |

---

## 2. What we built (shipped)

### 2.1 Phase map (done)

```
Phase 0 / PR-ML-A   Offline dataset + train (alert OHLCV labels)
Phase 0 / PR-ML-B   Live Auto-only score gate (kill switch)
Phase 0 / PR-ML-C   Retrain + autonomous promote (merit gate)
Phase 1a            trade_outcomes table + builder (executed round-trips)
Phase 1b            Hybrid labels: fill PnL preferred, alert fallback
Phase 1b ops        Prod SSM workflows, feature parse, weekly cron
```

### 2.2 Runtime — live BUY gate (PR-ML-B)

| Capability | Detail |
|------------|--------|
| Scope | **Auto** strategies only (`strategy_type == auto`) |
| Behavior | After rule BUY candidate, score with `current.joblib`; block if score &lt; threshold |
| Kill switch | `AUTO_ML_ENABLED` (prod: on) |
| Threshold | `AUTO_ML_THRESHOLD` (default `0.5`) |
| Shadow | `AUTO_ML_SHADOW_LOG` logs `[AUTO_ML]` scores |
| Fail-open | Missing model / `joblib` → allow rule BUY |
| Untouched | Swing / scalp / intraday |

**API status:** `GET /api/config/auto-ml`  
Fields include: `version`, `label_source`, `n_from_trade_outcome`, `n_from_alert`, `metrics`, `promote_reason`, `load_error`, `gate_enabled`.

### 2.3 Offline train & merit promote (PR-ML-A / C)

| Piece | Path / note |
|-------|-------------|
| Features + labels | `scripts/auto_ml_features.py` |
| Dataset builder | `scripts/build_auto_ml_dataset.py` |
| Train | `scripts/train_auto_entry_model.py` → `HistGradientBoostingClassifier` |
| Retrain + promote | `scripts/retrain_and_promote_auto_entry.py` |
| Merit logic | `backend/app/services/auto_entry_promote.py` |
| Prod artifacts | `/data/auto_ml/current.joblib`, `manifest.json` |
| Deps | `scripts/requirements-auto-ml.txt` (`joblib`, `scikit-learn`) |

**Promote guards:**

- `AUTO_ML_AUTONOMOUS_PROMOTE=true` for live path  
- `n_fit_rows ≥ AUTO_ML_PROMOTE_MIN_ROWS` (default 20)  
- Primary metric: holdout `roc_auc` (else accuracy) must improve by `≥ AUTO_ML_PROMOTE_MIN_DELTA`  
- **No** `--force-promote` in ops

### 2.4 Phase 1a — trade outcomes (executed fills)

| Piece | Path |
|-------|------|
| Migration | `backend/migrations/create_trade_outcomes.sql` |
| Model | `backend/app/models/trade_outcome.py` |
| Join / label | `backend/app/services/trade_outcome_builder.py` |
| CLI | `scripts/build_trade_outcomes.py --write-db` |

**COMPLETE label:** `y = 1` if round-trip `pnl_usd > 0`, else `0`.  
Join chain: telegram / intent → entry fill → exit (SL/TP/orphan flatten).

### 2.5 Phase 1b — hybrid training labels

| Mode | Flag | Label |
|------|------|--------|
| Alert (Phase 0) | `--label-source alert` | `dir_acc_1h OR tp_before_sl` |
| Fills only | `--label-source trade_outcomes` | COMPLETE `pnl_usd > 0` |
| **Hybrid (prod)** | `--label-source hybrid` | Prefer fill PnL; else alert-path |

**Important:** Phase 1b changes the **training dataset only**. Live gate code path and merit rules stay the same.

### 2.6 Feature engineering for fills (critical prod fix)

Prod `telegram_messages.context_json` usually **does not** store RSI/MA (diag: **0/2000** SIGNAL alerts). Indicators live in **message text**, e.g.:

```text
RSI=92.1 > 70 | MA50 90.27 < EMA10 91.33 | Volume 2.21x
```

**Built:**

- `parse_indicators_from_message` in `scripts/alert_quality_metrics.py`  
- Wired into feature extract + nearest-SIGNAL enrich (`scripts/auto_ml_features.py`)  
- Hybrid also keeps fill labels if features were previously dropped as “degraded”

**Result after fix:** `feature_rich=30` / `feature_degraded=0` → merit promote to **v12**.

### 2.7 Prod ops automation (GitHub Actions)

#### A) Ops — Auto ML hybrid retrain

| | |
|--|--|
| Workflow | `.github/workflows/ops-auto-ml-hybrid-retrain.yml` |
| Auth | OIDC → `AWS_DEPLOY_ROLE_ARN` → SSM → `i-087953603011543c5` → `backend-aws-1` |
| **Schedule** | **Monday 05:00 UTC — dry-run only** (no promote) |
| Manual dry-run | `workflow_dispatch` · `dry_run_only=true` · `days=90` |
| Manual promote | `workflow_dispatch` · `dry_run_only=false` · merit gate |

Steps: upsert `trade_outcomes` → hybrid retrain → print `DATASET_META` / manifest version.

#### B) Ops — Auto ML fill feature diag

| | |
|--|--|
| Workflow | `.github/workflows/ops-auto-ml-fill-diag.yml` |
| Mode | Read-only |
| Output | rich/degraded counts, donor pool, orphan COMPLETE rows |

### 2.8 Dashboard / product surface

| Item | Status |
|------|--------|
| Auto ML config in API | Shipped |
| VERSION_HISTORY entry for Phase 1b | v0.69 (#398) |
| Operator runbook | `docs/runbooks/auto_ml_entry.md` |
| ADR | ADR-0004 (entry classifier + autonomous promote) |

### 2.9 PR index (Phase 1b ops day — 2026-08-09)

| PR | Summary |
|----|---------|
| [#398](https://github.com/ccruz0/crypto-2.0/pull/398) | Hybrid labels + API fields + docs |
| [#415](https://github.com/ccruz0/crypto-2.0/pull/415)–[#418](https://github.com/ccruz0/crypto-2.0/pull/418) | Ops workflow, OIDC, `$DATABASE_URL`, `--write-db` |
| [#419](https://github.com/ccruz0/crypto-2.0/pull/419) | Load fills by days window |
| [#420](https://github.com/ccruz0/crypto-2.0/pull/420) | Keep degraded fill rows / alert feature fallback |
| [#421](https://github.com/ccruz0/crypto-2.0/pull/421)–[#423](https://github.com/ccruz0/crypto-2.0/pull/423) | Fill-feature diag + donor stats |
| [#424](https://github.com/ccruz0/crypto-2.0/pull/424)–[#425](https://github.com/ccruz0/crypto-2.0/pull/425) | Parse RSI/MA/Volume from SIGNAL message text |
| [#426](https://github.com/ccruz0/crypto-2.0/pull/426) | Orphan COMPLETE dump in diag |
| [#427](https://github.com/ccruz0/crypto-2.0/pull/427) | Weekly dry-run cron |

Earlier: PR-ML-A/B/C + Phase 1a trade_outcomes migration (see `docs/analysis/README.md`).

---

## 3. Training architecture (as built)

```
SIGNAL alert (Telegram)
        │
        ├─► Phase-0 path: OHLCV forward labels (dir@1h / TP before SL)
        │
        └─► order_intent → exchange entry/exit
                    │
                    ▼
         build_trade_outcomes.py --write-db
                    │
                    ▼
              trade_outcomes COMPLETE
                    │
                    ▼
     build_auto_ml_dataset.py --label-source hybrid
        • days-window COMPLETE fills
        • parse RSI/MA from message text
        • prefer fill PnL label; else alert label
                    │
                    ▼
     retrain_and_promote_auto_entry.py
        • holdout roc_auc
        • promote current.joblib only if improved
                    │
                    ▼
         /data/auto_ml/current.joblib
                    │
                    ▼
         Live Auto BUY gate (PR-ML-B)
```

---

## 4. Live production numbers (2026-08-09)

| Metric | Value |
|--------|--------|
| Model version | **12** |
| `label_source` | `hybrid` |
| `n_from_trade_outcome` | **30** |
| `n_from_alert` | **774** |
| Holdout AUC | **0.760** |
| Holdout accuracy | **0.687** |
| Promote | `metric_improved:0.7339→0.7598` |
| COMPLETE fills in DB | 32 (`with_alert=30`, orphan=2) |
| `load_error` | `null` |
| Gate / shadow | on / on |

**Orphans (excluded by design):**

| ID | Symbol | Why |
|----|--------|-----|
| 26 | ETH_USDT | Manual/orphan flatten · `intent.signal_id=null` |
| 32 | DOT_USD | same |

---

## 5. What we are planning to build (backlog)

Priority is **observe first**. Items below are **planned / optional**, not committed sprints.

### 5.1 Near-term (ops & quality) — when observe ends

| # | Planned item | Why | Status |
|---|--------------|-----|--------|
| P1 | Keep Monday dry-run cron; promote only when candidate &gt; live | Safe improve loop | **Active process** |
| P2 | Persist RSI/MA into `context_json` on **new** SIGNAL alerts | Fixes feature source at write time (backfill still uses message parse) | Not started |
| P3 | Dashboard polish — show hybrid fill counts / last promote clearly | Operators shouldn’t need raw API | Not started (API already has fields) |
| P4 | Grow trainable fill count organically | More COMPLETE Auto round-trips → stronger fill signal | Ongoing (market/time) |

### 5.2 Medium-term (model / data)

| # | Planned item | Why | Status |
|---|--------------|-----|--------|
| P5 | Richer features (ATR, volume consistency, strategy_index from config) | Message parse covers RSI/MA well; ATR often missing in text | Ideas |
| P6 | Optional OHLCV rebuild of indicators at `entry_ts` when message parse fails | Fallback for sparse message formats | Ideas |
| P7 | Investigate null `order_intents.signal_id` on manual paths | Root-cause for orphans — **not** required for Auto train set | Deferred (orphans left out by design) |
| P8 | Merit-promote on cron | Fully automatic promotes | **Rejected for now** (cron stays dry-run) |

### 5.3 Longer-term (product / Jarvis alignment)

| # | Planned item | Why | Notes |
|---|--------------|-----|--------|
| P9 | Calibrated threshold tuning from shadow logs | Reduce false blocks / missed filters | Needs shadow history |
| P10 | Per-symbol or regime models | Heterogeneous crypto names | Larger data requirement |
| P11 | Bounded rule tuning via Approval Center (ADR-0003 path) | Complementary to ML gate | Separate from entry classifier |
| P12 | Jarvis ACW must **not** auto-force ML promote | Keep human / merit gates | Already: no `--force-promote` in ops |

### 5.4 Explicitly out of scope (current pause)

- Rewriting swing/scalp gates with this model  
- Training on the 2 manual orphan fills without SIGNAL link  
- `--force-promote` to “make green”  
- Changing `HostSwapHigh` / unrelated host alerts  

---

## 6. How to operate (cheat sheet)

### Check live

```bash
curl -sS https://dashboard.hilovivo.com/api/config/auto-ml | jq '{
  version, label_source, n_from_trade_outcome, n_from_alert,
  trained_at, promoted_at, promote_reason, metrics, load_error,
  gate_enabled, shadow_log
}'
```

### Dry-run (safe)

GitHub → **Actions** → **Ops — Auto ML hybrid retrain** → Run workflow  
`dry_run_only=true`, `days=90`  

Or wait for **Monday 05:00 UTC** scheduled run.

### Live promote (human-gated)

Same workflow · `dry_run_only=false` · **only if** dry-run `candidate_metric ≥ current_metric`.

### Feature / orphan dig

**Ops — Auto ML fill feature diag** · `days=90` · inspect STDOUT JSON.

### Rollback

1. `AUTO_ML_ENABLED=false`, **or**  
2. Pin previous `current.joblib` / manifest on `/data/auto_ml`

---

## 7. Key files (repo map)

| Path | Role |
|------|------|
| `scripts/build_auto_ml_dataset.py` | Dataset · hybrid merge |
| `scripts/auto_ml_features.py` | Features · fill attach · enrich |
| `scripts/alert_quality_metrics.py` | Message indicator parse |
| `scripts/build_trade_outcomes.py` | Phase 1a upsert |
| `scripts/retrain_and_promote_auto_entry.py` | Train + merit promote |
| `scripts/diag_auto_ml_fill_features.py` | Prod fill diag |
| `backend/app/services/auto_entry_model.py` | Runtime load / score |
| `backend/app/services/auto_entry_promote.py` | Merit decision |
| `backend/app/services/trade_outcome_builder.py` | Fill joins |
| `.github/workflows/ops-auto-ml-hybrid-retrain.yml` | Cron + dispatch retrain |
| `.github/workflows/ops-auto-ml-fill-diag.yml` | Read-only diag |
| `docs/runbooks/auto_ml_entry.md` | Full operator runbook |
| `docs/project-history/architecture_decisions.md` | ADR-0004 |
| `AGENTS.md` | Agent ops notes |

---

## 8. Decisions log (session)

| Decision | Choice |
|----------|--------|
| Learn from fills | Hybrid labels (not fills-only) |
| Orphan COMPLETE without signal | **Exclude** from training |
| Cron promote? | **No** — dry-run only |
| Next coding focus | **Observe** gate + Monday cron |
| Source of RSI/MA for training | Parse SIGNAL **message text** (context_json empty in prod) |

---

## 9. One-line status

**Built:** Auto-only live gate + merit promote + Phase 1a outcomes + Phase 1b hybrid training (message-parsed features) + SSM ops + weekly dry-run cron — **v12 live**.  
**Planned next:** observe → then (optional) persist indicators in `context_json`, dashboard polish, grow fills, richer features — **no cron auto-promote**.

---

*For Notion import · Repo handover companion to `docs/runbooks/auto_ml_entry.md` · 2026-08-09*
