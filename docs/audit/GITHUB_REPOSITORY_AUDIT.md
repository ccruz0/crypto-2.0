# GitHub Repository Audit — ccruz0/crypto-2.0

**Date:** 2026-02-24 (re-run after PR #11 and #12 merged)  
**Scope:** GitHub configuration, workflows, secrets, permissions, branch protection, path-guard, egress.

---

## 1. Repository overview

| Item | Value |
|------|--------|
| **Repository** | `ccruz0/crypto-2.0` |
| **Default branch** | `main` |
| **Workflows** | 15 files in `.github/workflows/` |
| **path-guard.yml** | On `main` (merged via PR #11) |
| **Egress fixes** | On `main` (merged via PR #12) |
| **Dependabot** | `.github/dependabot.yml` — pip (backend), npm (frontend), weekly |
| **CODEOWNERS** | Not present |
| **actionlint** | `.github/actionlint.yaml` present |

---

## 2. Branch protection (ruleset)

**Ruleset:** `protect-main-production` (ID 13156283), **Active**, target: `main` (`~DEFAULT_BRANCH`).

| Rule | Configuration |
|------|----------------|
| **Deletion** | Enabled (block delete branch) |
| **Non–fast-forward** | Enabled (block force push) |
| **Pull request** | Required; 0 approving reviews; **required_review_thread_resolution: true**; merge methods: merge, squash, rebase |
| **Update** | Enabled (restrict updates) |
| **Required status checks** | **path-guard** only (GitHub Actions). Egress Security Audit not required (removed to allow PR #11 merge). |
| **Bypass list** | Empty; `current_user_can_bypass`: never (admin merge used for #11 and #12) |

**Recommendation:** To enforce Egress again, add **Egress Security Audit** back under “Status checks that are required” in Settings → Rules.

---

## 3. Workflow inventory

### 3.1 Summary

| Workflow | Trigger | Explicit permissions | Secrets used |
|----------|---------|----------------------|--------------|
| **path-guard.yml** | pull_request (main) | contents: read, pull-requests: read | None |
| **egress-audit.yml** | push/PR (main, develop), workflow_dispatch | contents: read, pull-requests: read | None |
| **no-inline-secrets.yml** | push/PR (main) | contents: read, pull-requests: read | None |
| **audit-pairs.yml** | push/PR (main, paths), workflow_dispatch | contents: read, pull-requests: read | None |
| **deploy.yml** | push (main) | contents: read, id-token: write | EC2_HOST, EC2_KEY, PUBLIC_BASE_URL, API_BASE_URL |
| **deploy_session_manager.yml** | push (main) | contents: read | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY |
| **restart_nginx.yml** | workflow_dispatch | contents: read | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY |
| **disable_all_trades.yml** | workflow_dispatch | contents: read | API_URL, API_KEY |
| **dashboard-data-integrity.yml** | push/PR (main, paths), workflow_dispatch | contents: read, pull-requests: write | DASHBOARD_URL, API_URL, BACKEND_URL, REPORT_SECRET |
| **aws-runtime-guard.yml** | push (main), workflow_dispatch | contents: read, pull-requests: read | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY |
| **aws-runtime-sentinel.yml** | push (main), workflow_dispatch | contents: read, pull-requests: read | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY |
| **security-scan.yml** | push/PR (main), workflow_dispatch | contents: read, security-events: write, actions: read | None |
| **security-scan-nightly.yml** | schedule, workflow_dispatch | contents: read, security-events: write, actions: read | None |
| **nightly-integrity-audit.yml** | schedule, workflow_dispatch | contents: read | None |

### 3.2 Explicit permissions (implemented)

All workflows now have explicit `permissions:` (minimal). Previously missing were added as follows:

- egress-audit, no-inline-secrets, audit-pairs: `contents: read`, `pull-requests: read`
- deploy_session_manager, restart_nginx, disable_all_trades: `contents: read`
- dashboard-data-integrity: `contents: read`, `pull-requests: write`
- deploy: `contents: read`, `id-token: write` (workflow level; job already had these)

---

## 4. Secrets used in workflows

| Secret | Workflows |
|--------|-----------|
| EC2_HOST, EC2_KEY, PUBLIC_BASE_URL, API_BASE_URL | deploy.yml |
| AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY | deploy_session_manager, restart_nginx, aws-runtime-guard, aws-runtime-sentinel |
| API_URL, API_KEY | disable_all_trades, dashboard-data-integrity |
| DASHBOARD_URL, BACKEND_URL, REPORT_SECRET | dashboard-data-integrity |

All uses are via `${{ secrets.* }}`; no plain values in workflow YAML. Keep these in Settings → Secrets and variables → Actions.

---

## 5. Path Guard (on main)

- **File:** `.github/workflows/path-guard.yml`
- **Trigger:** pull_request to `main`
- **Behavior:** Fails the job if the PR touches any protected path. **No label bypass.**

**Protected paths:**

- `backend/app/api/routes_control.py`, `routes_manual_trade.py`, `routes_orders.py`
- `backend/app/services/brokers/crypto_com_trade.py`
- `backend/app/core/runtime.py`, `backend/app/utils/trading_guardrails.py`, `backend/app/core/telegram_secrets.py`
- `secrets/`, `.env.aws`, `.env.prod.example`, `secrets/runtime.env.example`
- `nginx/dashboard.conf`, `docker-compose.yml`, `backend/Dockerfile.aws`, `.github/workflows/deploy.yml`

---

## 6. Egress Security Audit

- **File:** `.github/workflows/egress-audit.yml`
- **Triggers:** push / pull_request (main, develop), workflow_dispatch
- **Steps:** `scripts/security/egress_audit.py`; pytest `backend/tests/test_static_http_imports.py`; grep checks for direct HTTP imports/calls.

**Status:** Direct HTTP imports have been centralized in `backend/app/utils/http_client.py` (PR #12). Egress audit and static HTTP import tests are expected to pass on branches that include that fix.

---

## 7. .gitignore and secrets

- **.gitignore:** Covers `.env`, `.env.aws`, `.env.local`, `.env.lab`, and variants; `secrets/*`, `secrets/pg_password`, `secrets/runtime.env`.
- **Compose:** `no-inline-secrets` workflow and `scripts/aws/check_no_inline_secrets_in_compose.sh` enforce no inline secrets in compose files.

---

## 8. Security summary

| Aspect | Status |
|--------|--------|
| path-guard on main | ✅ Merged (PR #11); required in ruleset |
| Egress HTTP imports | ✅ Fixed on main (PR #12) |
| Required status checks | path-guard only; Egress optional |
| Minimal permissions | ✅ All workflows have explicit minimal permissions |
| Secret handling | ✅ Only `secrets.*` in workflows; .gitignore and no-inline-secrets in place |
| Dependabot | ✅ Configured (pip, npm, weekly) |
| CODEOWNERS | Not configured (optional) |

---

## 9. Recommendations

1. **Re-add Egress Security Audit** as a required check in the ruleset if you want it to block merges again (main already has the fix). *(Manual: Settings → Rules.)*
2. **Add explicit `permissions:`** — **Done:** Added to egress-audit, no-inline-secrets, audit-pairs, deploy_session_manager, restart_nginx, disable_all_trades, dashboard-data-integrity, and deploy.yml.
3. **Add `.env.lab`** — **Done:** Added to `.gitignore`.
4. **Bypass list:** Optionally add an admin/maintainer bypass for the ruleset so merges are possible when checks are temporarily failing. *(Manual: Settings → Rules → Bypass list.)*

---

## 10. References

- Path guard and label bypass: `docs/openclaw/LABEL_BYPASS_AUDIT_REPORT.md`, `docs/openclaw/VERIFICATION_QUICK_CHECKLIST.md`
- OpenClaw: `docs/openclaw/ARCHITECTURE.md`, `docs/openclaw/SECURITY.md`
- Inline secrets: `scripts/aws/check_no_inline_secrets_in_compose.sh`, `tests/security/test_inline_secrets_checker.sh`
- HTTP client (egress): `backend/app/utils/http_client.py`; tests: `backend/tests/test_static_http_imports.py`
