# PR #32 Deployment Readiness Audit

**Date:** 2026-06-09  
**PR:** [#32 Complete GitHub App runtime authentication](https://github.com/ccruz0/crypto-2.0/pull/32) (`fix/github-app-runtime-completion`)  
**Method:** Repository file analysis only — no production shell access  
**Scenario under test:** `GITHUB_APP_*` missing, `GITHUB_TOKEN` present, `ALLOW_LEGACY_GITHUB_PAT` absent, `ATP_TRADING_ONLY=1`

---

## Executive summary

| Gate | Result |
|------|--------|
| **Container startup after PR #32 deploy** | **PASS** — `ATP_TRADING_ONLY=1` skips GitHub auth startup checks |
| **Deploy workflow (GitHub Actions → SSM → EC2)** | **CONDITIONAL PASS** — succeeds if EC2 project path exists and `render_runtime_env.sh` runs; **FAIL** if canonical path is `crypto-2.0` only |
| **Runtime GitHub API calls without render** | **FAIL** — `get_github_api_token()` returns `auth_method=none` when `ALLOW_LEGACY_GITHUB_PAT` absent |
| **Runtime GitHub API calls after successful render** | **PASS** — render auto-sets `ALLOW_LEGACY_GITHUB_PAT=true` when PAT-only |

**Bottom line:** PR #32 deployment is **safe for trading** (`ATP_TRADING_ONLY=1` contains startup risk). Automation paths that call GitHub API will **fail** until `render_runtime_env.sh` runs and sets the legacy escape hatch — or until GitHub App SSM parameters exist.

---

## 1. Exact runtime behaviour (post-PR #32)

### Auth resolution (`get_github_api_token()`)

Source: `backend/app/services/github_app_auth.py`

| Condition | Token returned | `auth_method` |
|-----------|----------------|---------------|
| All three `GITHUB_APP_*` set and PEM loads | Installation access token (minted or cached) | `github_app` |
| App mint fails + `ALLOW_LEGACY_GITHUB_PAT=true` + `GITHUB_TOKEN` set | PAT value | `legacy_pat` |
| App not configured + `ALLOW_LEGACY_GITHUB_PAT=true` + `GITHUB_TOKEN` set | PAT value | `legacy_pat` |
| App not configured + `ALLOW_LEGACY_GITHUB_PAT` absent + `GITHUB_TOKEN` set | `""` (empty) | `none` |
| Nothing configured | `""` | `none` |

**Test scenario (App missing, PAT present, flag absent):** `auth_method=none` — all GitHub API consumers receive empty token.

### Consumers migrated in PR #32

| Consumer | File | Behaviour when `auth_method=none` |
|----------|------|-----------------------------------|
| Deploy dispatch | `backend/app/services/deploy_trigger.py` | Returns `ok: false`, error: *"GitHub API auth unavailable"* |
| Cursor bridge PR creation | `backend/app/services/cursor_execution_bridge.py` | Returns `ok: false`, error: *"GitHub API auth unavailable"* |
| Dashboard data integrity dispatch | `backend/app/api/routes_monitoring.py` | Raises `ValueError` → HTTP 500 |

### Pre-PR #32 behaviour (main branch today on EC2)

`deploy_trigger.py` reads `GITHUB_TOKEN` directly — **works** with PAT present regardless of `ALLOW_LEGACY_GITHUB_PAT`.

---

## 2. Exact deployment behaviour

Source: `.github/workflows/deploy_session_manager.yml`

### Sequence on `push` to `main` or `workflow_dispatch`

```
1. Checkout repo in Actions runner (crypto-2.0)
2. Clone frontend in Actions runner
3. Configure AWS credentials (repository secrets)
4. SSM RunShellScript → EC2:
   a. cd /home/ubuntu/automated-trading-platform (fallback ~/automated-trading-platform)
   b. Fetch SSM /automated-trading-platform/prod/github_token
   c. Write GITHUB_TOKEN to .env.aws AND secrets/runtime.env (NO ALLOW_LEGACY_GITHUB_PAT)
5. SSM RunShellScript → EC2:
   a. cd automated-trading-platform
   b. git pull origin main
   c. Clone frontend
6. SSM RunShellScript → EC2:
   a. cd automated-trading-platform
   b. bash scripts/aws/render_runtime_env.sh  (|| continue on failure)
   c. docker compose --profile aws down/build/up
   d. Health wait on localhost:8002/ping_fast
   e. nginx restart
```

### PR #32 impact on deploy step 6b (`render_runtime_env.sh`)

After PR #32, when SSM PAT exists and App keys absent:

```
GITHUB_AUTH_MODE=legacy_transition
ALLOW_LEGACY_GITHUB_PAT=true   ← auto-written
GITHUB_TOKEN=<from SSM>
```

This **repairs** the gap left by step 4 (PAT inject without flag).

### Deploy failure modes (scenario under test)

| Failure point | Cause | Trading impact |
|---------------|-------|----------------|
| Step 4/5/6: `Cannot find project directory` | EC2 canonical path is `/home/ubuntu/crypto-2.0` but workflow only checks `automated-trading-platform` | **Deploy fails** — containers not rebuilt; trading continues on old image |
| Step 6b: `render_runtime_env.sh` fails | SSM telegram keys missing, AWS creds unavailable | Workflow **continues** with existing `runtime.env` — may lack `ALLOW_LEGACY_GITHUB_PAT` |
| Step 6c: docker build fails | Unrelated to GitHub auth | Deploy fails; old containers may keep running |
| Step 6c: backend health wait timeout | Slow startup or crash | Workflow reports warning; may still be running old code |

**Deploy itself does not fail** due to missing `GITHUB_APP_*` — those are optional in render script.

---

## 3. Startup behaviour

Source: `backend/app/factory.py`, `docker-compose.yml`

### `ATP_TRADING_ONLY=1` (production today)

| Check | Behaviour |
|-------|-----------|
| GitHub App startup validation | **Skipped** — logs: *"ATP_TRADING_ONLY=1 — deploy/agent secrets not required"* |
| `RuntimeError` for bare PAT without App | **Not raised** — check gated behind `not is_atp_trading_only()` |
| `RuntimeError` for missing GitHub auth | **Not raised** — same gate |
| Agent router mount | **Not mounted** (`agent_router = None`) |
| Governance router mount | **Not mounted** (`governance_router = None`) |
| Monitoring router mount | **Mounted** (always) |
| Agent scheduler loop | **Skipped** |
| Cursor bridge startup log | **Skipped** |
| Notion startup validation | **Skipped** |
| Telegram poller / commands | **Runs** if `RUN_TELEGRAM=true` and `RUN_TELEGRAM_POLLER=true` |

### `ATP_TRADING_ONLY=0` (future full automation)

With scenario under test (PAT, no App, no `ALLOW_LEGACY`):

| Check | Behaviour |
|-------|-----------|
| Startup | **`RuntimeError`** — *"GITHUB_TOKEN in environment is no longer supported on AWS without GitHub App"* |
| Container | **Crash loop** until `ALLOW_LEGACY_GITHUB_PAT=true` or App credentials added |

---

## 4. Automation behaviour

### Agent scheduler

- **Status with `ATP_TRADING_ONLY=1`:** Disabled — no Notion task pickup, no automatic pipeline execution.
- **GitHub auth impact:** None at scheduler level (scheduler not running).

### Required secrets registry (`required_secrets_registry.py`)

- GitHub App keys listed as required for automation enablement.
- With `ATP_TRADING_ONLY=1`, automation-required secrets are not enforced at startup.

---

## 5. Telegram deploy behaviour

Source: `backend/app/services/telegram_commands.py`, `deploy_trigger.py`

Telegram poller and approval callbacks **are not gated** by `ATP_TRADING_ONLY`. Deploy approval can still be triggered via Telegram when trading-only mode is on.

### Deploy approval flow

| Path | Trigger | GitHub auth used |
|------|---------|------------------|
| Legacy Telegram deploy | `deploy_approve` callback → `trigger_deploy_workflow()` | `get_github_api_token()` |
| Governed deploy (`ATP_GOVERNANCE_AGENT_ENFORCE`) | `execute_governed_manifest()` → `agent_deploy_bundle` → `trigger_deploy_workflow()` | Same |

### Scenario under test (post-PR #32, before render)

| Step | Result |
|------|--------|
| User taps Deploy Approve in Telegram | Callback fires |
| `trigger_deploy_workflow()` called | `token=""`, `auth_method=none` |
| User sees | *"Deploy trigger failed — GitHub API auth unavailable"* |
| Notion status | May already be set to `deploying` |

### After successful `render_runtime_env.sh`

| Step | Result |
|------|--------|
| `ALLOW_LEGACY_GITHUB_PAT=true` + `GITHUB_TOKEN` present | `auth_method=legacy_pat` |
| `trigger_deploy_workflow()` | HTTP 204 from GitHub → deploy workflow dispatched |
| User sees | *"Deploy triggered"* |

### Cursor bridge via Telegram (`run_cursor_bridge`)

- **Not gated** by `ATP_TRADING_ONLY`.
- Phase 2 run (`create_pr=False` in Telegram path) does not require GitHub auth for apply+tests.
- PR creation (API path or `create_pr=True`) requires `get_github_api_token()` — fails with `auth_method=none` in test scenario.

---

## 6. Governance deploy behaviour

Source: `backend/app/api/routes_governance.py`, `governance_executor.py`

| Mode | `ATP_TRADING_ONLY=1` behaviour |
|------|-------------------------------|
| Governance REST API (`/api/governance/*`) | **403** — `governance_api_disabled` |
| Telegram governed deploy (`ATP_GOVERNANCE_AGENT_ENFORCE=true`) | Governance Python modules import and execute — **not blocked by trading-only flag** at import level |
| `agent_deploy_bundle` step | Calls `trigger_deploy_workflow()` — same auth rules as Telegram legacy path |

**Note:** Governance HTTP API is disabled in trading-only mode, but Telegram-governed deploy path can still invoke `governance_executor` if enforcement flag is set.

---

## 7. Cursor bridge behaviour

Source: `backend/app/services/cursor_execution_bridge.py`

| Operation | Auth required | Scenario result |
|-----------|---------------|-------------------|
| Staging provision + CLI + tests | No GitHub auth | Works |
| `create_patch_pr()` | `get_github_api_token()` | **Fails** — `auth_method=none` |
| `_github_auth_configured()` | Uses `github_api_token_configured()` | Returns `false` |

Startup logs Cursor bridge config only when `ATP_TRADING_ONLY=0`.

---

## 8. Verification script

Source: `scripts/verify_deploy_secrets.sh`

After PR #32 deploy, running on EC2:

| Scenario | `auth_mode` reported | `Deploy automation ready?` |
|----------|---------------------|---------------------------|
| PAT + `ALLOW_LEGACY_GITHUB_PAT=true` (post-render) | `legacy_transition` | **YES** |
| PAT without `ALLOW_LEGACY` (pre-render / render failed) | `none` | **NO** (exit 1) |
| All three App keys present | `github_app` | **YES** |

**Gap:** Deploy workflow does **not** invoke `verify_deploy_secrets.sh`.

---

## 9. Decision matrix: would deployment fail?

| Component | Fails? | Condition |
|-----------|--------|-----------|
| Backend startup | **No** | `ATP_TRADING_ONLY=1` |
| Docker compose rebuild | **Maybe** | Wrong EC2 path |
| `render_runtime_env.sh` | **No** | PAT in SSM is sufficient input |
| GitHub API at runtime (if invoked) | **Yes** | Until render sets `ALLOW_LEGACY_GITHUB_PAT` |
| Trading engine | **No** | No trading logic changes in PR #32 |

---

## 10. Recommended pre-deploy checklist (operator, no code changes)

1. Confirm EC2 active repo path (`crypto-2.0` vs `automated-trading-platform`) — see [deploy_target_path_validation.md](./deploy_target_path_validation.md).
2. Merge PR #32.
3. Deploy via workflow or manual pull on correct path.
4. On EC2: `bash scripts/aws/render_runtime_env.sh` — confirm output includes `GITHUB_AUTH_MODE=legacy_transition` and `ALLOW_LEGACY_GITHUB_PAT=YES`.
5. `docker compose --profile aws up -d --force-recreate backend-aws`.
6. `./scripts/verify_deploy_secrets.sh` — expect `auth_mode: legacy_transition`.
7. Keep `ATP_TRADING_ONLY=1` until GitHub App SSM populated and smoke-tested.

---

## Related files

| File | Role |
|------|------|
| `backend/app/services/github_app_auth.py` | Central auth |
| `backend/app/services/deploy_trigger.py` | Deploy dispatch |
| `backend/app/services/cursor_execution_bridge.py` | PR creation |
| `backend/app/api/routes_monitoring.py` | Integrity workflow dispatch |
| `backend/app/factory.py` | Startup gates |
| `scripts/aws/render_runtime_env.sh` | Secret render + `ALLOW_LEGACY` auto-set |
| `scripts/verify_deploy_secrets.sh` | Post-deploy verification |
| `.github/workflows/deploy_session_manager.yml` | Primary deploy path |
