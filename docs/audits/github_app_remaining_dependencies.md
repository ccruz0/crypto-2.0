# GitHub App Migration — Remaining PAT Dependencies Audit

**Date:** 2026-06-09  
**Scope:** Repository `/home/ubuntu/crypto-2.0` (branch `main` + open PR #32 `fix/github-app-runtime-completion`)  
**Method:** Full-text search for `GITHUB_TOKEN`, `github_token`, `ghp_`, `workflow_dispatch`, `Authorization:`, `token`, `Bearer`  
**Production context (confirmed):** SSM `GITHUB_APP_*` absent; `/automated-trading-platform/prod/github_token` present; `ATP_TRADING_ONLY=1`; `ALLOW_LEGACY_GITHUB_PAT` absent in prod; deploy workflow still injects PAT; GitHub App not yet created.

---

## Classification legend

| # | Category | Meaning |
|---|----------|---------|
| 1 | **Runtime critical** | Backend process reads env or calls GitHub API at runtime |
| 2 | **Deploy critical** | CI/CD or deploy path writes/fetches PAT into production runtime |
| 3 | **Operator script** | Manual/SSM helper used by operators (not automatic runtime) |
| 4 | **OpenClaw only** | LAB OpenClaw / GHCR / token-file paths (not PROD backend default) |
| 5 | **Test only** | Unit/integration tests and fixtures |
| 6 | **Documentation only** | Docs, examples, comments, runbooks |

---

## 1. Runtime critical

These paths affect or gate PROD backend GitHub API authentication when `ATP_TRADING_ONLY=0`.

| File | Match / usage | Notes |
|------|---------------|-------|
| `backend/app/services/github_app_auth.py` | `GITHUB_TOKEN`, `GITHUB_APP_*`, `Bearer`, `Authorization` | Central auth: mints App installation tokens; legacy PAT only if `ALLOW_LEGACY_GITHUB_PAT=true` |
| `backend/app/services/deploy_trigger.py` | `GITHUB_TOKEN`, `workflow_dispatch`, `Bearer` | Telegram/governance deploy dispatch via `get_github_api_token()` |
| `backend/app/services/cursor_execution_bridge.py` | `GITHUB_TOKEN`, `GITHUB_APP_*`, `Bearer` | Patch PR creation via `get_github_api_token()` |
| `backend/app/api/routes_monitoring.py` | `github_token`, `Bearer`, `workflow_dispatch` | `dashboard_data_integrity` workflow dispatch |
| `backend/app/factory.py` | `GITHUB_TOKEN`, `ALLOW_LEGACY_GITHUB_PAT` | Startup fail-fast when not trading-only; blocks bare PAT on AWS without escape hatch |
| `backend/app/services/required_secrets_registry.py` | `GITHUB_TOKEN`, `GITHUB_APP_*`, `ALLOW_LEGACY_GITHUB_PAT` | Dashboard secret catalog and missing-secret detection |
| `backend/app/api/routes_admin.py` | `ALLOW_LEGACY_GITHUB_PAT` | Admin diagnostics: `github_legacy_pat_active` flag |
| `backend/entrypoint.sh` | `GITHUB_TOKEN` (comment + `source secrets/runtime.env`) | Loads all runtime secrets into Python process |
| `scripts/aws/render_runtime_env.sh` | `github_token`, `GITHUB_TOKEN`, `GITHUB_APP_*`, `ALLOW_LEGACY_GITHUB_PAT` | **Authoritative secret render** from SSM → `secrets/runtime.env` |
| `secrets/runtime.env.example` | `GITHUB_TOKEN`, `GITHUB_APP_*`, `ALLOW_LEGACY_GITHUB_PAT` | Template (not loaded in prod directly) |

**Production nuance:** With `ATP_TRADING_ONLY=1`, `factory.py` **skips** GitHub App startup checks. Deploy/automation code is present but not validated at startup until trading-only mode is disabled.

---

## 2. Deploy critical

These inject or depend on PAT during deploy; they do **not** call GitHub API from the backend but shape runtime env.

| File | Match / usage | Notes |
|------|---------------|-------|
| `.github/workflows/deploy_session_manager.yml` | `github_token`, `GITHUB_TOKEN`, `workflow_dispatch` | Step 1: SSM PAT inject into `.env.aws` + `secrets/runtime.env`; step 3: runs `render_runtime_env.sh` |
| `deploy_all.sh` | Same PAT inject + `render_runtime_env.sh` mirror | Manual equivalent of deploy workflow |
| `deploy_github_token_ssm.sh` | `GITHUB_TOKEN`, `github_token`, `ghp_` | Operator script to push PAT to EC2 `.env.aws` via SSM |

**Redundancy note:** PAT inject (lines 61–80 of `deploy_session_manager.yml`) duplicates what `render_runtime_env.sh` already does when run later in the same workflow (line 158). After App cutover, both steps need updating or removal.

---

## 3. Operator script

| File | Match / usage | Notes |
|------|---------------|-------|
| `scripts/verify_deploy_secrets.sh` | `GITHUB_TOKEN`, `GITHUB_APP_*`, `ALLOW_LEGACY_GITHUB_PAT` | Post-deploy verification (container env presence) |
| `scripts/set_github_token_for_deploy.sh` | `GITHUB_TOKEN`, `ghp_` | Interactive PAT → `secrets/runtime.env` |
| `scripts/set_github_token_popup.py` | `ghp_`, `GITHUB_TOKEN` | macOS/GUI PAT entry helper |
| `scripts/test_deploy_dispatch.sh` | `GITHUB_TOKEN`, `Bearer`, `workflow_dispatch` | Host curl test against GitHub Actions API |
| `backend/scripts/test_deploy_dispatch.sh` | Same | In-container variant |
| `verificar_deploy.sh` | `GITHUB_TOKEN`, `Authorization: token` | Checks legacy `deploy.yml` workflow runs (not `deploy_session_manager.yml`) |

---

## 4. OpenClaw only

| File | Match / usage | Notes |
|------|---------------|-------|
| `scripts/openclaw/store_ghcr_token.sh` | `ghp_`, token | LAB GHCR login helper |
| `scripts/openclaw/store_pat_and_install.sh` | `OPENCLAW_PAT=ghp_` | LAB PAT storage |
| `scripts/openclaw/ghcr_login_lab.md` | `ghp_` | LAB GHCR docs |
| `scripts/openclaw/prompt_github_token.sh` | `github_token` | LAB token prompt |
| `docs/openclaw/DEPLOYMENT.md` | `OPENCLAW_GITHUB_TOKEN`, `GITHUB_TOKEN` | LAB compose env |
| `docs/openclaw/AUDIT_TOKEN_CONSUMPTION.md` | `GITHUB_TOKEN`, `GH_TOKEN`, `Bearer` | OpenClaw token-file audit |
| `docs/openclaw/BUILD_AND_PUSH_OPENCLAW_IMAGE.md` | `ghp_`, `secrets.GITHUB_TOKEN` | GHCR / CI token guidance |
| `docs/openclaw/ARCHITECTURE.md` | `GITHUB_TOKEN` | LAB vs CI comparison |
| `docs/openclaw/VERIFY_OPENCLAW_CONTAINER.md` | `ghp_`, `Bearer`, `GITHUB_TOKEN` | Container verification |
| `docs/openclaw/LAB_SETUP_AND_VALIDATION.md` | `Bearer`, GitHub API curl examples | Manual LAB validation |
| `docs/openclaw/FINAL_SECURITY_CHECKLIST.md` | `ghp_`, `Bearer` | LAB security checklist |
| `docs/openclaw/.github/workflows/docker_publish.yml` | `secrets.GITHUB_TOKEN`, `workflow_dispatch` | **OpenClaw repo** GHCR publish (not ATP backend) |
| `docs/openclaw/CURSOR_PROMPT_OPENCLAW_GHCR_WORKFLOW.md` | `secrets.GITHUB_TOKEN` | Prompt template |
| `docs/openclaw/APPLY_GHCR_WORKFLOW.md` | `secrets.GITHUB_TOKEN` | Apply guide |
| SSM fallback path `/openclaw/github-token` | Referenced in deploy inject scripts | Legacy OpenClaw token path used as PAT fallback during deploy inject |

**Not PROD backend:** OpenClaw uses `OPENCLAW_TOKEN_FILE` / `.env.lab`; separate from EC2 `secrets/runtime.env` GitHub App path.

---

## 5. Test only

| File | Match / usage |
|------|---------------|
| `backend/tests/test_github_app_auth.py` | `ghp_test`, `ghp_legacy`, `GITHUB_TOKEN`, `GITHUB_APP_*` |
| `backend/tests/test_deploy_trigger_auth.py` | Mocks `get_github_api_token` |
| `backend/tests/test_required_secrets_registry.py` | `ghp_xx`, `GITHUB_TOKEN`, `ALLOW_LEGACY_GITHUB_PAT` |

---

## 6. Documentation only

| File | Topic |
|------|-------|
| `backend/docs/GITHUB_APP_AUTH.md` | Canonical GitHub App + legacy PAT runbook |
| `docs/runbooks/secrets_runtime_env.md` | SSM paths, legacy PAT |
| `docs/runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md` | Deploy trigger, webhook |
| `docs/runbooks/governance_approval_flow.md` | `Bearer` (governance API, not GitHub) |
| `docs/runbooks/TASK_STUCK_IN_DEPLOYING.md` | `GITHUB_WEBHOOK_SECRET` |
| `docs/architecture/CURSOR_EXECUTION_BRIDGE_DESIGN.md` | Historical `GITHUB_TOKEN` wording |
| `docs/architecture/OPENCLAW_AUTONOMOUS_RECOVERY_DESIGN.md` | Deploy trigger |
| `docs/audit/EGRESS_HARDENING_DESIGN.md` | `GITHUB_TOKEN`, workflow dispatch |
| `docs/audit/MAC_MINI_OPENCLAW_MIGRATION_PLAN.md` | GitHub App note |
| `docs/audit/GITHUB_REPOSITORY_AUDIT.md` | Workflow inventory |
| `docs/aws/README.md` | `workflow_dispatch` on guard workflows |
| `docs/WORKFLOW_STATUS_GUIDE.md` | Deploy workflow |
| `docs/monitoring/HEALTH_MONITORING.md` | Example workflow |
| `docs/openclaw/*` (additional) | Security, architecture, prompts |
| `docs/governance/CONTROL_PLANE_TASK_VIEW.md` | Governance Bearer auth |
| `docs/agents/multi-agent/*` | OpenClaw Bearer |
| `docs/GATEWAY_MODEL_ROUTING*.md` | OpenClaw Bearer |
| `VERIFICATION_STATUS.md`, `TELEGRAM_*.md`, `docs/ORDER_CANCELLATION*.md` | API Bearer (not GitHub) |

---

## `workflow_dispatch` inventory (trigger mechanism — mostly not PAT-related)

| File | Category | Uses PAT? |
|------|----------|-----------|
| `backend/app/services/deploy_trigger.py` | 1 Runtime | Uses App/PAT token to **call** dispatch API |
| `.github/workflows/deploy_session_manager.yml` | 2 Deploy | Workflow **target**; PAT injected separately |
| `.github/workflows/deploy.yml` | 2 Deploy (legacy SSH) | No PAT in workflow |
| `.github/workflows/disable_all_trades.yml` | 6 Doc/workflow | API_URL/API_KEY only |
| `.github/workflows/restart_nginx.yml` | 6 | AWS secrets |
| `.github/workflows/aws-runtime-guard.yml` | 6 | AWS secrets |
| `.github/workflows/aws-runtime-sentinel.yml` | 6 | AWS secrets |
| `.github/workflows/security-scan*.yml` | 6 | None |
| `.github/workflows/egress-audit.yml` | 6 | None |
| `.github/workflows/dashboard-data-integrity.yml` | 1 Runtime (dispatched by backend) | Backend supplies token |
| Other audit/guard workflows | 6 | None |

---

## `Authorization:` / `Bearer` — GitHub vs non-GitHub

### GitHub API (PAT or installation token)

| File | Category |
|------|----------|
| `backend/app/services/github_app_auth.py` | 1 — App JWT + installation token |
| `backend/app/services/deploy_trigger.py` | 1 |
| `backend/app/api/routes_monitoring.py` | 1 |
| `backend/app/services/cursor_execution_bridge.py` | 1 (PR push/create) |
| `scripts/test_deploy_dispatch.sh` | 3 |
| `backend/scripts/test_deploy_dispatch.sh` | 3 |
| `verificar_deploy.sh` | 3 — uses legacy `Authorization: token` header |

### Non-GitHub Bearer (excluded from PAT migration)

| Area | Examples |
|------|----------|
| OpenClaw gateway | `scripts/check_openclaw_health.sh`, `docs/openclaw/*` |
| Governance/agent API | `routes_governance.py`, `routes_agent.py` |
| Trading API | `test_strategy_api.sh`, `verify_strategy_fix.sh` |
| Tavily extension | `openclaw-home-data/extensions/openclaw-tavily/*` |

---

## SSM parameter map (PAT vs App)

| SSM path | Type | Category |
|----------|------|----------|
| `/automated-trading-platform/prod/github_token` | PAT (exists in prod) | 2 Deploy / 1 Runtime (via render) |
| `/openclaw/github-token` | PAT fallback in inject scripts | 2 Deploy / 4 OpenClaw legacy |
| `/automated-trading-platform/prod/github_app/app_id` | App ( **not in prod** ) | 1 Runtime |
| `/automated-trading-platform/prod/github_app/installation_id` | App ( **not in prod** ) | 1 Runtime |
| `/automated-trading-platform/prod/github_app/private_key_b64` | App ( **not in prod** ) | 1 Runtime |
| `/automated-trading-platform/lab/github_app/*` | App LAB fallback in render script | 1 Runtime |

---

## Summary counts (unique actionable paths)

| Category | Count (approx.) | Action for cutover |
|----------|-----------------|-------------------|
| Runtime critical | 10 files | Already migrated to `get_github_api_token()` in PR #32; needs SSM App creds + `ATP_TRADING_ONLY=0` to activate |
| Deploy critical | 3 files | Remove/redundant PAT inject after App SSM populated |
| Operator script | 6 files | Update docs; deprecate PAT setters after cutover |
| OpenClaw only | 15+ files | **Out of scope** for PROD backend cutover |
| Test only | 3 files | Keep; update if legacy path removed |
| Documentation only | 25+ files | Update after cutover |

---

## Key finding

**Runtime API call sites are migrated in PR #32** to centralized GitHub App auth. **Remaining PAT surface is infrastructure:** SSM `github_token`, deploy workflow PAT injection, `render_runtime_env.sh` legacy path, and operator scripts — not direct `GITHUB_TOKEN` reads in application dispatch code (pre-PR #32 on `main`, post-PR #32 in branch).
