# GitHub App Transition — Deployment Impact Analysis

**Date:** 2026-06-09  
**Assumptions:**
- PR #33 (path canonicalization) **merged**
- PR #32 (GitHub App auth gate in backend) **merged**
- GitHub App **does not exist** yet
- SSM `github_app/*` **absent**
- PAT **present** in SSM `/automated-trading-platform/prod/github_token`
- Transition commit **merged** and deployed via CI

---

## 1. What happens after backend restart?

### If transition commit deployed + `render_runtime_env.sh` ran successfully

| Step | Outcome |
|------|---------|
| `runtime.env` contains `GITHUB_TOKEN` + `ALLOW_LEGACY_GITHUB_PAT=true` | Yes |
| `factory.py` startup | **Passes** — `github_api_token_configured()` true via legacy escape hatch |
| Log | `ALLOW_LEGACY_GITHUB_PAT=true — using GITHUB_TOKEN for GitHub API` (warning) |
| Trading | **Unaffected** — no trading code changes |
| Container | **Starts normally** |

### If transition commit NOT deployed OR render did not run

| Step | Outcome |
|------|---------|
| `GITHUB_TOKEN` present, `ALLOW_LEGACY_GITHUB_PAT` absent | **RuntimeError** at startup |
| Message | *"GITHUB_TOKEN in environment is no longer supported on AWS without GitHub App"* |
| Container | **Fails healthcheck / crash loop** |

---

## 2. What happens to `deploy_trigger`?

**Module:** `backend/app/services/deploy_trigger.py`

| State | Behavior |
|-------|----------|
| Transition active (`ALLOW_LEGACY` + `GITHUB_TOKEN`) | `get_github_api_token()` → `auth_method=legacy_pat`, returns PAT |
| `trigger_deploy_workflow()` | **Succeeds** — POST to GitHub Actions `workflow_dispatch` with PAT bearer token |
| Telegram / governance callers | Deploy approval → workflow dispatch **works** |

| State | Behavior |
|-------|----------|
| No auth (`auth_method=none`) | Returns `ok: false`, error: *"Configure GITHUB_APP_* or ALLOW_LEGACY_GITHUB_PAT=true with GITHUB_TOKEN"* |

**Impact:** Transition commit **restores** deploy dispatch that PR #32 would block without `ALLOW_LEGACY`.

---

## 3. What happens to `routes_monitoring`?

**Relevant path:** `dashboard_data_integrity` workflow trigger (lines ~2730–2769)

| State | Behavior |
|-------|----------|
| Transition active | `get_github_api_token()` returns PAT → GitHub API dispatch **works** |
| No auth | `ValueError: GitHub API auth unavailable` → workflow trigger **fails** with 500 |

Other monitoring routes unaffected — no auth logic changes in this commit.

---

## 4. What happens to `cursor_execution_bridge`?

**Module:** `backend/app/services/cursor_execution_bridge.py` — `create_patch_pr()`

| State | Behavior |
|-------|----------|
| Transition active | `get_github_api_token()` → PAT → PR creation via GitHub API **works** |
| No auth | Returns `{ok: false, error: "GitHub API auth unavailable..."}` |

**Impact:** Cursor bridge PR flow continues on PAT during transition.

---

## 5. What happens to Telegram deploy approval?

**Call chain:** `telegram_commands.py` → `trigger_deploy_workflow()` → `get_github_api_token()`

| State | Behavior |
|-------|----------|
| Transition active + backend running | User approves deploy → PAT dispatches `deploy_session_manager.yml` → **works** |
| Backend failed startup (no ALLOW_LEGACY) | Telegram bot may be down or deploy command fails at API level |
| Deploy dispatched successfully | CI runs on `main` as today; path now targets `crypto-2.0` (PR #33) |

**Note:** PAT is **not removed** — explicitly preserved for transition.

---

## 6. What happens if `render_runtime_env.sh` succeeds?

During CI deploy (`deploy_session_manager.yml` step):

```
bash scripts/aws/render_runtime_env.sh || { echo "⚠️ render_runtime_env failed; continuing..." && true; }
```

**On success (with transition commit):**

1. Fetches PAT from SSM → writes `GITHUB_TOKEN`
2. No App keys → sets `ALLOW_LEGACY_GITHUB_PAT=true`
3. Prints `GITHUB_AUTH_MODE=legacy_transition`
4. `docker compose --profile aws up -d --build` loads new env
5. Backend starts with legacy PAT auth
6. `./scripts/verify_deploy_secrets.sh` → `auth_mode: legacy_transition`

---

## 7. What happens if `render_runtime_env.sh` fails?

Workflow **continues** (non-fatal `|| true`).

| Scenario | Effect |
|----------|--------|
| Previous `runtime.env` had `ALLOW_LEGACY=true` | Backend may still start |
| Previous env has PAT but no `ALLOW_LEGACY` | Backend **may fail startup** after container recreate |
| Previous env stale / missing PAT | Backend **fails** deploy auth check |

**Mitigation:** Manual render on EC2 or fix SSM connectivity; transition commit does not change fail-soft behavior.

---

## Summary matrix

| Component | Without transition commit | With transition commit |
|-----------|--------------------------|------------------------|
| Backend startup (PAT-only) | **FAIL** | **PASS** |
| `deploy_trigger` | **FAIL** | **PASS** |
| `routes_monitoring` GitHub dispatch | **FAIL** | **PASS** |
| `cursor_execution_bridge` PRs | **FAIL** | **PASS** |
| Telegram deploy approval | **FAIL** | **PASS** |
| Trading | Unaffected | Unaffected |
| OpenClaw | Unaffected | Unaffected |

---

## Future state (after GitHub App provisioned)

When App SSM parameters exist and render runs:
- `ALLOW_LEGACY_GITHUB_PAT` auto-removed
- `auth_method=github_app`
- PAT can be revoked in separate operator step (not in this commit)
