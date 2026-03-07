# OpenClaw — Security Audit and Safeguards

**Phase 1** is the Repository & CI Audit. **Phase 5** safeguards (path protection and CI gate) are specified here and in `ARCHITECTURE.md`; this document focuses on the audit report and the security checklist.

---

## Phase 1 — Repository & CI Audit Report

### 1.1 Repo Hosting Platform

| Item | Finding |
|------|--------|
| **Platform** | **GitHub** |
| **Repository** | `ccruz0/crypto-2.0` (references in docs; workspace may be `automated-trading-platform`) |
| **Remote** | `https://github.com/ccruz0/crypto-2.0.git` (from docs/audits and README) |
| **GitLab** | Not used (no `.gitlab-ci.yml` or GitLab references) |

---

### 1.2 CI Status

| Item | Finding |
|------|--------|
| **CI system** | **GitHub Actions** |
| **Workflows** | Multiple workflows under `.github/workflows/` |
| **Trigger branches** | Primarily **main**; `egress-audit.yml` also triggers on **develop** |
| **Deploy** | `deploy.yml` runs on **push to main** (deploy to EC2 via SSH/rsync) |

**Workflows identified:**

| Workflow | Trigger | Purpose |
|----------|---------|--------|
| deploy.yml | push (main) | Deploy to AWS EC2 |
| deploy_session_manager.yml | push (main) | SSM/session manager related deploy |
| security-scan.yml | push/PR (main), dispatch | Trivy image + FS scan |
| no-inline-secrets.yml | push/PR (main) | Block inline secrets in compose |
| aws-runtime-guard.yml | push (main), dispatch | AWS runtime verification |
| aws-runtime-sentinel.yml | (review) | Runtime sentinel |
| dashboard-data-integrity.yml | push/PR (main) | Dashboard data integrity |
| audit-pairs.yml | push/PR (main) | Trading pairs audit |
| disable_all_trades.yml | (workflow_dispatch) | Disable all trades |
| egress-audit.yml | push/PR (main, develop) | Egress audit |
| nightly-integrity-audit.yml | (scheduled) | Nightly integrity |
| restarts, others | (varies) | Nginx restart, etc. |

**Conclusion:** CI is configured and active; deployment is tied to `main`.

---

### 1.3 Branch Protections

| Item | Finding |
|------|--------|
| **Branch protection (API)** | Not auditable from repo content alone; must be checked in GitHub: Settings → Branches. |
| **Assumption** | This audit **cannot verify** from the repository whether branch protection rules are enabled. |
| **Recommendation** | Ensure **main** (and **develop** if used) have: require PR, required status checks (Trivy, no-inline-secrets, audit-pairs, path-guard), no direct push, no force push. |

**Action for operator:** In GitHub → Repository → Settings → Branches, add or edit rule for `main`: require pull request, require status checks, require up-to-date branch, restrict pushes (e.g. allow OpenClaw to push only to `openclaw/*` via PAT/deploy key, not to main).

---

### 1.4 Current Branching Strategy

| Branch | Role | Evidence |
|--------|------|----------|
| **main** | Default; deployment target; primary integration branch | deploy.yml, security-scan.yml, no-inline-secrets.yml, audit-pairs, etc. |
| **develop** | Optional long-lived dev branch | egress-audit.yml triggers on main + develop |
| **audit/ec2-aws-snapshot** | Feature/audit branch | From git status (current branch in snapshot) |
| **Other** | Short-lived feature branches | Standard Git flow |

**Conclusion:** Main-based flow with optional develop; no formal “git-flow” or “trunk-based” doc in repo; workflows assume `main` as the deployment branch.

---

### 1.5 Presence of Secrets in Repo

| Check | Finding |
|-------|--------|
| **.gitignore** | `.env`, `.env.aws`, `.env.local`, `secrets/*` (with exceptions for `.gitkeep`, `runtime.env.example`), `secrets/pg_password`, `secrets/runtime.env` are ignored. |
| **Compose inline secrets** | CI workflow `no-inline-secrets.yml` + `scripts/aws/check_no_inline_secrets_in_compose.sh` scan compose files and fail on inline secret-like keys (token, password, api_key, etc.). Values must be via `${VAR}` or env_file. |
| **Hardcoded secrets in code** | No scan was run for literal API keys/passwords in source; config uses `os.getenv` / pydantic Settings. Some scripts (e.g. `ops/encrypt_telegram_*.py`) handle tokens from env/file; they are not committed. |
| **.env.aws in repo** | `.env.aws` is in `.gitignore`; if present on disk it should not be committed. Audit cannot guarantee it was never committed in history. |
| **Example files** | `.env.local.example`, `.env.prod.example`, `secrets/runtime.env.example` are present; they contain variable names and placeholders, not live secrets. |

**Immediate risks:**

1. **Branch protection unknown:** If branch protection is not enabled, direct pushes to `main` could bypass CI and deploy.
2. **Secrets in history:** If `.env.aws` or `secrets/runtime.env` were ever committed, they remain in Git history; consider rotation and `git filter-repo`/BFG if needed.
3. **Deploy key on EC2:** Deploy uses `EC2_KEY` (SSH key) and `EC2_HOST` from GitHub secrets; ensure these are repository secrets and not logged.
4. **Path protection:** No CI path-guard yet; changes to trading/control/secrets paths are not automatically gated (see Phase 5).

**Security gaps:**

- No automated check that **protected paths** (trading, secrets, endpoint config) require explicit approval (see Phase 5 and ARCHITECTURE.md).
- Branch protection status not verifiable from repo; must be confirmed in GitHub UI/API.

---

### 1.6 Structured Audit Summary

| Section | Result |
|---------|--------|
| **Repo hosting platform** | GitHub (`ccruz0/crypto-2.0`) |
| **CI status** | GitHub Actions configured; multiple workflows; deploy on push to main |
| **Branch protections** | Not verifiable from repo; must be set in GitHub |
| **Branching strategy** | main = default/deploy; develop optional; feature branches |
| **Secrets in repo** | Mitigated by .gitignore and no-inline-secrets CI; no guarantee for history |
| **Security gaps** | Branch protection unverified; no path-guard for sensitive files |
| **Immediate risks** | Direct push to main if unprotected; secrets in history; no path safeguard |

---

## Phase 5 — Safeguards (Summary)

- **Prevent modification of trading execution files without manual approval:** Implement path-guard CI that fails PRs that touch protected paths unless the PR has a security approval label or is from an allowed actor (see ARCHITECTURE.md §8).
- **Prevent secret file edits:** Include `secrets/*`, `.env.aws`, and example secret templates in the protected path list; path-guard blocks or requires approval.
- **Prevent endpoint modification without review:** Include `nginx/dashboard.conf`, `docker-compose.yml`, and deploy workflow in protected paths; path-guard enforces approval.
- **CI security gate:** New workflow `path-guard.yml` (or equivalent name) runs on PRs, lists changed files, and fails if any match protected paths and the PR does not have the required label/approval.

Detailed list of protected paths and logic is in **ARCHITECTURE.md §8**. Implementation blueprint for the path-guard workflow is in **DEPLOYMENT.md**.

---

## Security Checklist (Pre- and Post–OpenClaw)

### Pre–OpenClaw (Repository and Prod)

- [ ] Confirm branch protection on `main`: require PR, require status checks (Trivy, no-inline-secrets, audit-pairs), no force push, no deletion.
- [ ] Confirm no production secrets in repo or in Git history; rotate if ever exposed.
- [ ] Verify GitHub Actions secrets: `EC2_HOST`, `EC2_KEY`, `PUBLIC_BASE_URL`/`API_BASE_URL`, etc. are repository secrets (not in logs).
- [ ] Add path-guard workflow and required status check for protected paths (see DEPLOYMENT.md).
- [ ] Document protected paths in ARCHITECTURE.md and keep in sync with path-guard.

### Lab Instance (OpenClaw)

- [ ] Lab EC2 has no `.env.aws`, no `secrets/runtime.env`, no `secrets/telegram_key` from production.
- [ ] Only `.env.lab` (and optional local test env) on Lab; contents: repo URL, GitHub PAT or deploy key path, no prod credentials.
- [ ] OpenClaw container: non-root, read-only root FS where possible, cap_drop ALL, no-new-privileges, resource limits.
- [ ] Lab security group egress: only GitHub (and any other required APIs); no access to prod VPC/RDS/EC2.
- [ ] OpenClaw can only push to non-protected branches (e.g. `openclaw/*`); merge to main only via PR + review.

### Post–OpenClaw (Ongoing)

- [ ] Rotate OpenClaw PAT/deploy key periodically.
- [ ] Review path-guard failures and ensure no bypass without approval.
- [ ] Keep Trivy and no-inline-secrets checks passing; fix HIGH/CRITICAL before merging.
- [ ] Audit who can add `security-approved` (or equivalent) label; restrict to maintainers.

---

## Document References

- **ARCHITECTURE.md** — Target architecture, Git model, branch protection, CI checks, secrets model, network egress, Docker hardening, and full safeguard design.
- **DEPLOYMENT.md** — Implementation blueprint: folder structure, docker-compose.openclaw.yml, systemd, .env.lab template, path-guard workflow spec, deployment steps.
- **COST_MODEL.md** — Instance type, resource limits, logging, and estimated monthly cost.
