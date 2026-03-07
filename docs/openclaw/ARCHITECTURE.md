# OpenClaw — Secure AWS Lab Architecture

**Purpose:** Design a secure architecture where the Production Trading Instance is isolated from the Lab Instance that runs OpenClaw permanently. OpenClaw can clone the repo, create branches, open PRs, and run tests; it cannot access production secrets, execute real trades, or access the production database.

**See also:** [ARCHITECTURE_V1_1_INTERNAL_SERVICE.md](ARCHITECTURE_V1_1_INTERNAL_SERVICE.md) — Dashboard ↔ OpenClaw UI (internal service model, Nginx proxy, no public 8080).

---

## 1. High-Level Architecture

### 1.1 Environment Separation

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AWS ap-southeast-1 (VPC)                             │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────────────────────────────────┐  ┌──────────────────────────────────┐ │
│  │  PRODUCTION (atp-rebuild-2026)        │  │  LAB (atp-lab-ssm-clean)          │ │
│  │  ─────────────────────────────────    │  │  ─────────────────────────────    │ │
│  │  • backend-aws (RUNTIME_ORIGIN=AWS)   │  │  • OpenClaw container only       │ │
│  │  • market-updater-aws                 │  │  • RUNTIME_ORIGIN=LOCAL           │ │
│  │  • frontend-aws, db, nginx            │  │  • No backend/frontend stack      │ │
│  │  • Real trading, Telegram, DB         │  │  • No production secrets          │ │
│  │  • secrets/runtime.env, .env.aws      │  │  • .env.lab only (read-only repo) │ │
│  └──────────────────────────────────────┘  └──────────────────────────────────┘ │
│           │                                              │                      │
│           │ No network path Lab → Prod                    │                      │
│           │ (separate security groups, no shared VPC      │ Egress: GitHub API,  │
│           │  peering for app traffic)                     │ 443 only             │
│           ▼                                              ▼                      │
│  ┌─────────────────┐                          ┌─────────────────┐               │
│  │ api.crypto.com  │                          │ api.github.com  │               │
│  │ api.telegram.org│                          │ (clone, PR, API)│               │
│  └─────────────────┘                          └─────────────────┘               │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 OpenClaw Capabilities Matrix

| Capability                    | Allowed | Implementation |
|------------------------------|--------|-----------------|
| Clone repository             | Yes    | Deploy key or fine-grained PAT (repo read) |
| Create branches              | Yes    | PAT with `contents: write` (or push via deploy key with write) |
| Open Pull Requests           | Yes    | GitHub API with PAT or GitHub App |
| Run tests (CI or local)      | Yes    | Trigger GitHub Actions or run in container (no prod deps) |
| Read public repo content     | Yes    | No token needed for public; PAT for private |
| Access production secrets    | No     | Lab instance has no .env.aws, no secrets/runtime.env from prod |
| Execute real trades          | No     | No exchange keys on Lab; no backend-aws with TRADING_ENABLED |
| Access production database   | No     | No DATABASE_URL to prod; Lab may have local DB for tests only |
| Modify protected paths      | No     | CI + branch protection + path restrictions (see Safeguards) |

---

## 2. Git Permission Model

### 2.1 Recommended: Deploy Key + Limited PAT

- **Deploy key (read-only, optional):** Attach to repo for clone-only. Use for automation that only needs pull.
- **Fine-grained Personal Access Token (PAT) or GitHub App:** For OpenClaw to create branches and open PRs.

**Scopes (fine-grained PAT, repository access: this repo only):**

| Permission     | Access   | Reason |
|----------------|----------|--------|
| Contents       | Read and write | Clone, branch, push (to non-protected branches) |
| Pull requests  | Read and write | Create/update PRs |
| Metadata       | Read     | Required |
| Workflows      | Read (optional) | See workflow status; do not need write |

**What NOT to grant:** Admin, secrets, environments, variables, or any other repo.

### 2.2 Deploy Key (Alternative for Clone + Push to Non-Protected Branches)

- Generate ED25519 key on Lab instance: `ssh-keygen -t ed25519 -C "openclaw-lab" -f /etc/openclaw/deploy_key -N ""`
- Add as **deploy key** in GitHub: Settings → Deploy keys → Add (read-only or read-write).
- If read-write: OpenClaw can push to branches that are **not** protected (e.g. `openclaw/*`). Use branch protection so `main` (and optionally `develop`) require PR + reviews.

---

## 3. Branch Protection Requirements

Apply to `main` (and optionally `develop` if used):

| Setting | Value | Reason |
|---------|--------|--------|
| Require pull request before merging | Yes | All changes via PR |
| Required approvals | 1 (or more) | Human review for main |
| Dismiss stale reviews | Yes | Re-review after new commits |
| Require status checks | Yes | e.g. `Security Scan (Trivy)`, `No inline secrets`, `audit-pairs`, `path-guard` (new) |
| Require branch up to date | Yes | Avoid bypassing CI |
| Restrict who can push | No direct push | Only via PR; allow OpenClaw to push to `openclaw/*` |
| Allow force push | No | |
| Allow deletion | No | |

**Branch strategy (current + recommendation):**

- **main:** Default branch; deployment target; protected.
- **develop:** Referenced in `egress-audit.yml`; optional long-lived dev branch; protect if used.
- **openclaw/*** or **lab/***:** Short-lived branches created by OpenClaw; not protected; merge only via PR to main/develop.

---

## 4. Required CI Checks (for Protected Branches)

These must pass before merge to main (and develop if protected):

| Workflow / Check | Purpose |
|------------------|--------|
| No inline secrets in compose | Already present; blocks inline secrets in compose files |
| Security Scan (Trivy) | Image + FS scan; fail on HIGH/CRITICAL |
| audit-pairs | Trading pairs audit |
| Path guard (new) | Block changes to protected paths unless allowed (see Safeguards) |
| Deploy (optional as required check) | Only if you want “deploy must succeed” as gate (risky; usually use “deploy on main” without requiring success for merge) |

---

## 5. Secrets Management Model

| Secret / Config | Production | Lab (OpenClaw) |
|-----------------|------------|----------------|
| .env.aws        | Present (EC2 prod) | **Never** present |
| secrets/runtime.env | Present (prod) | **Never** present |
| secrets/telegram_key | Present (prod) | **Never** present |
| DATABASE_URL    | Prod PostgreSQL | Not set, or local/test DB only |
| TELEGRAM_*      | Set on prod | Not set |
| EXCHANGE / CRYPTO keys | Prod only | Not set |
| GITHUB_TOKEN / PAT | In CI only (GitHub Actions) | In .env.lab (Lab-only PAT or deploy key) |
| .env.lab        | Not used | Only on Lab; contains OPENCLAW_GITHUB_TOKEN, repo URL, etc. |

**Principle:** Lab instance has no copy of production env files or secrets. OpenClaw runs with a dedicated identity (PAT or deploy key) and only has access to repo + GitHub API, not to ATP production resources.

---

## 6. Network Egress Restrictions (Lab)

Restrict Lab instance security group egress to minimize blast radius:

| Type  | Port | Destination | Purpose |
|-------|------|-------------|---------|
| HTTPS | 443 | api.github.com, *.github.com | Clone, PR, API |
| HTTPS | 443 | Optional: other APIs (e.g. for tests) | Only if needed |
| DNS   | 53  | VPC DNS or 0.0.0.0/0 | Resolution |
| HTTP  | 80  | 169.254.169.254/32 | IMDS (if used) |

**Explicitly do NOT allow (from Lab):**

- Production RDS/VPC endpoints
- Production EC2 private IPs
- api.crypto.com (unless Lab runs non-trading tests that need public market data only; then restrict to public endpoints only, no private API keys)

---

## 7. Docker Hardening Configuration (OpenClaw)

- **User:** Run as non-root (e.g. `user: "1000:1000"` or dedicated user in image).
- **Read-only root filesystem:** Where possible (`read_only: true`); use tmpfs for writable dirs (e.g. `/tmp`, clone target).
- **No privileged, no new privileges:** `security_opt: - no-new-privileges:true`, no `privileged: true`.
- **Capabilities:** Drop all: `cap_drop: - ALL`.
- **Resource limits:** CPU and memory limits (see COST_MODEL.md).
- **No mounts of host secrets:** Do not mount `.env.aws`, `secrets/`, or any prod credential path.
- **Environment:** Only `env_file: .env.lab` and explicit non-secret vars; no `.env.aws` or `secrets/runtime.env`.
- **Network:** Use a dedicated Docker network; no connection to prod stack.

See `DEPLOYMENT.md` for full `docker-compose.openclaw.yml` and `.env.lab` template.

---

## 8. Safeguards (Phase 5) — Protected Paths and CI Gate

### 8.1 Protected Paths (Require Manual Approval or Block)

- **Trading execution and critical control:**
  - `backend/app/api/routes_control.py`
  - `backend/app/api/routes_manual_trade.py`
  - `backend/app/api/routes_orders.py`
  - `backend/app/services/brokers/crypto_com_trade.py`
  - `backend/app/core/runtime.py`
  - `backend/app/utils/trading_guardrails.py`
- **Secrets and credential handling:**
  - `backend/app/core/telegram_secrets.py` (if exists)
  - `secrets/*` (any change to files under `secrets/`)
  - `.env.aws`, `.env.prod.example`, `secrets/runtime.env.example`
- **Endpoint and deployment:**
  - `nginx/dashboard.conf`
  - `docker-compose.yml` (production profiles and env_file references)
  - `backend/Dockerfile.aws`
  - `.github/workflows/deploy.yml`

**Policy:**

1. **CI security gate:** A new workflow (e.g. `path-guard.yml`) runs on every PR and fails if changes touch protected paths **and** the PR is not labeled (e.g. `security-approved`) or not from an allowed actor.
2. **Branch protection:** Require status checks including this path-guard so that unauthorized changes to protected paths cannot merge.
3. **Manual approval:** Changes to the above paths should require explicit review and optionally a `security-approved` label (or similar) before merge.

### 8.2 Path-Guard Logic (Text Specification)

- On pull_request (and optionally push to main), list changed files.
- If any changed file matches the protected path list:
  - **Allow** if: PR has label `security-approved` (or similar) **or** author is in an allowed list (e.g. org owners).
  - **Otherwise fail** the check and post a comment explaining that changes to protected paths require security review/approval.

### 8.3 Diagram: Safeguards in the Pipeline

```
                    PR opened / push to main
                              │
                              ▼
                    ┌─────────────────────┐
                    │  path-guard.yml     │
                    │  (list changed      │
                    │   files)            │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
    No protected paths   Protected paths   Protected paths
    touched              + label           no label
              │          security-approved  │
              │                │            │
              ▼                ▼            ▼
         ✅ Pass         ✅ Pass        ❌ Fail
         (other CI       (allowed       (comment:
          runs)           after review)   "Require security
                                          review for …")
```

---

## 9. Summary

- **Production** remains on its own EC2 instance with full secrets and trading capability; no OpenClaw or Lab services run there.
- **Lab** runs only OpenClaw in a hardened container with Git + GitHub API access, no production secrets, and no trading or production DB access.
- **Git** uses a deploy key and/or a limited PAT with minimal scopes (contents, pull requests, metadata).
- **Branch protection** and **CI checks** (including a new path-guard) ensure protected paths are not changed without review.
- **Secrets** are strictly separated: prod on prod instance only; Lab uses only `.env.lab` and no prod env or secret files.

Implementation details, folder structure, and step-by-step deployment are in `DEPLOYMENT.md`. Cost and resource sizing are in `COST_MODEL.md`. Audit findings and security checklist are in `SECURITY.md`.
