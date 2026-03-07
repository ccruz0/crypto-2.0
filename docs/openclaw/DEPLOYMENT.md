# OpenClaw — Implementation Blueprint and Deployment Guide

This document provides the folder structure, hardened Docker Compose file, systemd service, `.env.lab` template, GitHub token scope requirements, security checklist reference, and step-by-step deployment guide. **Existing ATP services are not removed or modified** by this blueprint; OpenClaw is additive (Lab instance only).

---

## 1. Folder Structure

Recommended layout for OpenClaw on the Lab instance and in the repo:

```
automated-trading-platform/          # or crypto-2.0 (repo root)
├── .github/
│   └── workflows/
│       └── path-guard.yml           # NEW: CI security gate for protected paths
├── docs/
│   └── openclaw/
│       ├── ARCHITECTURE.md
│       ├── COST_MODEL.md
│       ├── DEPLOYMENT.md
│       └── SECURITY.md
├── docker-compose.yml               # EXISTING (unchanged)
├── docker-compose.openclaw.yml      # NEW: OpenClaw stack (Lab only)
├── .env.lab.example                # NEW: template for Lab env (no secrets)
├── scripts/
│   └── openclaw/
│       ├── openclaw.service         # systemd unit (or in docs/openclaw/)
│       ├── start_openclaw.sh        # optional wrapper
│       └── path_guard_protected.txt  # list of protected paths for CI
└── openclaw/                        # optional: OpenClaw app/config if in-repo
    └── .gitkeep
```

On the **Lab EC2** host (e.g. `/home/ubuntu/automated-trading-platform` or `~/lab-repo`):

```
/home/ubuntu/
├── automated-trading-platform/     # clone of repo (read-only for OpenClaw or dedicated clone)
│   ├── docker-compose.openclaw.yml
│   ├── .env.lab                    # from .env.lab.example; never commit
│   └── ...
├── openclaw-data/                  # optional: persistent dir for clone/output
│   └── workspace/
└── /var/log/openclaw/              # host log dir (create + logrotate)
```

---

## 2. Hardened docker-compose.openclaw.yml

Use this file **only on the Lab instance**. Do not use it on Production. It does not reference `.env.aws` or `secrets/runtime.env`.

```yaml
# docker-compose.openclaw.yml
# Lab only. Do NOT use on Production. No production secrets.
# Run: docker compose -f docker-compose.openclaw.yml up -d

name: openclaw-lab

services:
  openclaw:
    image: ${OPENCLAW_IMAGE:-ghcr.io/your-org/openclaw:latest}
    # Or build from repo: build: ./openclaw (if Dockerfile exists)
    container_name: openclaw
    env_file:
      - .env.lab
    environment:
      - OPENCLAW_MODE=lab
      - RUNTIME_ORIGIN=LOCAL
      - GIT_REPO_URL=${GIT_REPO_URL}
      - GITHUB_TOKEN=${OPENCLAW_GITHUB_TOKEN}
    volumes:
      - openclaw_workspace:/workspace
      - openclaw_logs:/var/log/openclaw
    # No mount of .env.aws, secrets/, or any prod path
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:size=128M,mode=1777
    user: "1000:1000"
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 2G
        reservations:
          memory: 512M
    networks:
      - openclaw_net
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  openclaw_workspace:
  openclaw_logs:

networks:
  openclaw_net:
    driver: bridge
```

**Notes:**

- Replace `OPENCLAW_IMAGE` / build path with your actual OpenClaw image or build context.
- If the image does not support `read_only: true`, remove it and rely on non-root + cap_drop.
- `OPENCLAW_GITHUB_TOKEN` and `GIT_REPO_URL` come from `.env.lab` (not committed).

---

## 3. systemd Service File

This keeps OpenClaw running under Docker Compose after reboot. Install to `/etc/systemd/system/openclaw.service`.

```ini
# /etc/systemd/system/openclaw.service
# Lab instance only. Starts OpenClaw stack via Docker Compose.

[Unit]
Description=OpenClaw Lab Stack
Documentation=file:///home/ubuntu/automated-trading-platform/docs/openclaw/DEPLOYMENT.md
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/automated-trading-platform
ExecStartPre=/usr/bin/docker compose -f docker-compose.openclaw.yml pull --quiet
ExecStart=/usr/bin/docker compose -f docker-compose.openclaw.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.openclaw.yml down
TimeoutStartSec=120
TimeoutStopSec=60
User=ubuntu
Group=ubuntu

[Install]
WantedBy=multi-user.target
```

**Install steps (on Lab host):**

```bash
sudo cp /home/ubuntu/automated-trading-platform/scripts/openclaw/openclaw.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openclaw
sudo systemctl start openclaw
sudo systemctl status openclaw
```

---

## 4. .env.lab Template

Create `.env.lab` on the Lab instance from this template. **Do not commit `.env.lab`**; add it to `.gitignore` if not already covered.

**File: `.env.lab.example` (safe to commit):**

```bash
# .env.lab.example — copy to .env.lab on Lab instance and fill values.
# Do NOT commit .env.lab. Do NOT use production secrets here.

# Repo to clone and work with (HTTPS or SSH URL)
GIT_REPO_URL=https://github.com/ccruz0/crypto-2.0.git

# GitHub token for OpenClaw (create fine-grained PAT with minimal scope)
# Scopes: Contents read+write, Pull requests read+write, Metadata read
OPENCLAW_GITHUB_TOKEN=

# Optional: path to deploy key (if using SSH instead of PAT)
# OPENCLAW_DEPLOY_KEY_PATH=/etc/openclaw/deploy_key

# OpenClaw image (if using pre-built image)
OPENCLAW_IMAGE=ghcr.io/your-org/openclaw:latest

# Optional: branch to base work on
OPENCLAW_BASE_BRANCH=main

# Optional: log level
OPENCLAW_LOG_LEVEL=INFO
```

**On Lab host:** `cp .env.lab.example .env.lab` and set at least `GIT_REPO_URL` and `OPENCLAW_GITHUB_TOKEN`.

---

## 5. GitHub / GitLab Token Scope Requirements

### 5.1 Fine-grained Personal Access Token (GitHub)

- **Repository access:** Only this repository (or select repos).
- **Permissions:**
  - **Contents:** Read and write (clone, push to non-protected branches).
  - **Pull requests:** Read and write (create/update PRs).
  - **Metadata:** Read (required).
- **Do not grant:** Administration, Secrets, Environments, Variables, Actions write (optional: Actions read to see workflow status).

### 5.2 Classic PAT (alternative)

- Scopes: `repo` (full control of private repos) is sufficient but broader than needed; prefer fine-grained.
- If classic: `repo` only; no `admin:org`, no `delete_repo`, no `workflow`.

### 5.3 Deploy Key (alternative to PAT)

- Add deploy key in GitHub → Settings → Deploy keys.
- Read-only: clone only. Read-write: clone + push to branches the key is allowed to push to.
- Restrict push via branch protection so this key cannot push to `main` (only to e.g. `openclaw/*`).

---

## 6. Security Checklist (Reference)

- [ ] Lab instance has no `.env.aws`, no `secrets/runtime.env`, no `secrets/telegram_key`.
- [ ] Only `.env.lab` on Lab; contains only `GIT_REPO_URL`, `OPENCLAW_GITHUB_TOKEN` (or deploy key path), and non-secret options.
- [ ] OpenClaw container: non-root, `cap_drop: ALL`, `no-new-privileges`, resource limits (1 CPU, 2G RAM).
- [ ] Lab security group egress: only GitHub (and required APIs); no prod VPC/DB.
- [ ] Branch protection on `main`: require PR, require status checks (including path-guard).
- [ ] Path-guard workflow added and required for protected paths (see below).

Full checklist: **SECURITY.md**.

---

## 7. CI Security Gate: Path-Guard Workflow

Add a workflow that fails PRs touching protected paths unless the PR has an approval label (e.g. `security-approved`).

**Protected paths list** (keep in sync with ARCHITECTURE.md):

- `backend/app/api/routes_control.py`
- `backend/app/api/routes_manual_trade.py`
- `backend/app/api/routes_orders.py`
- `backend/app/services/brokers/crypto_com_trade.py`
- `backend/app/core/runtime.py`
- `backend/app/utils/trading_guardrails.py`
- `backend/app/core/telegram_secrets.py`
- `secrets/`
- `.env.aws`
- `.env.prod.example`
- `secrets/runtime.env.example`
- `nginx/dashboard.conf`
- `docker-compose.yml`
- `backend/Dockerfile.aws`
- `.github/workflows/deploy.yml`

**Workflow spec (`.github/workflows/path-guard.yml`):**

- **Trigger:** `pull_request` (types: opened, synchronize) and optionally `push` to `main`.
- **Steps:**
  1. Checkout repo.
  2. List changed files (e.g. `git diff --name-only origin/main...HEAD` or `github.event.pull_request` API).
  3. For each changed file, check if it matches any protected path (prefix or exact).
  4. If any match: check if PR has label `security-approved` (or similar) or author is in allowed list (e.g. from repo config).
  5. If protected path touched and not allowed → fail job and optionally comment on PR.
  6. Otherwise pass.

**Example (pseudo):**

```yaml
# .github/workflows/path-guard.yml
name: Path Guard
on:
  pull_request:
    branches: [main]
jobs:
  path-guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Get changed files
        id: changed
        run: |
          FILES=$(git diff --name-only origin/main...HEAD 2>/dev/null || git diff --name-only HEAD^ HEAD)
          echo "files<<EOF" >> $GITHUB_OUTPUT
          echo "$FILES" >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT
      - name: Check protected paths
        env:
          PROTECTED_PATHS: |
            backend/app/api/routes_control.py
            backend/app/api/routes_manual_trade.py
            backend/app/api/routes_orders.py
            backend/app/services/brokers/crypto_com_trade.py
            backend/app/core/runtime.py
            backend/app/utils/trading_guardrails.py
            secrets/
            .env.aws
            nginx/dashboard.conf
            docker-compose.yml
            backend/Dockerfile.aws
            .github/workflows/deploy.yml
        run: |
          # Compare each changed file against protected list;
          # if any match and PR does not have label 'security-approved', exit 1
          # (Implementation: script that reads $GITHUB_EVENT_PATH for labels and changed files)
```

A full implementation would parse `github.event.pull_request.labels` and `github.event.pull_request.files` (or use the API) to decide pass/fail. Add this workflow as a **required status check** for `main` in branch protection.

---

## 8. Step-by-Step Deployment Guide

### 8.1 Prerequisites

- AWS Lab EC2 instance (e.g. t3.small) in ap-southeast-1, with Docker and Docker Compose v2 installed.
- No production env files or secrets on this instance.
- GitHub fine-grained PAT (or deploy key) for OpenClaw with scopes in §5.

### 8.2 On the Lab Instance

1. **Clone the repo (once):**
   ```bash
   cd /home/ubuntu
   git clone https://github.com/ccruz0/crypto-2.0.git automated-trading-platform
   cd automated-trading-platform
   ```

2. **Create `.env.lab`:**
   ```bash
   cp .env.lab.example .env.lab
   chmod 600 .env.lab
   # Edit and set GIT_REPO_URL, OPENCLAW_GITHUB_TOKEN (and OPENCLAW_IMAGE if needed)
   nano .env.lab
   ```

3. **Create log directory and (optional) logrotate:**
   ```bash
   sudo mkdir -p /var/log/openclaw
   sudo chown ubuntu:ubuntu /var/log/openclaw
   ```

4. **Start OpenClaw with Compose:**
   ```bash
   docker compose -f docker-compose.openclaw.yml up -d
   docker compose -f docker-compose.openclaw.yml ps
   docker compose -f docker-compose.openclaw.yml logs -f openclaw
   ```

5. **Install systemd service (optional, for persistence across reboot):**
   ```bash
   sudo cp scripts/openclaw/openclaw.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable openclaw
   sudo systemctl start openclaw
   ```

### 8.3 In GitHub

1. Add branch protection rule for `main`: require PR, require status checks (Security Scan, No inline secrets, audit-pairs, Path Guard when added), no force push.
2. Add workflow `.github/workflows/path-guard.yml` and add “Path Guard” as required status check.
3. Create fine-grained PAT (or deploy key), store in `.env.lab` as `OPENCLAW_GITHUB_TOKEN` (or configure deploy key path).

### 8.4 Verification

- OpenClaw container is running: `docker compose -f docker-compose.openclaw.yml ps`.
- OpenClaw can clone repo (if your image/script performs clone): check logs.
- OpenClaw cannot access production: ensure no `.env.aws` or `secrets/` on Lab; ensure Lab SG has no access to prod.

---

## 9. What Was Not Changed

- **Production stack:** `docker-compose.yml` and all existing services (backend-aws, frontend-aws, db, market-updater-aws, nginx, etc.) are unchanged.
- **Existing workflows:** No removal or modification of deploy.yml, security-scan.yml, no-inline-secrets.yml, etc.; only **addition** of path-guard.yml and OpenClaw-specific files.
- **Secrets:** No production secrets are introduced into the repo; `.env.lab` is local to Lab and not committed.

---

## 10. Document Index

| Document | Content |
|----------|---------|
| **ARCHITECTURE.md** | Target architecture, Git model, branch protection, CI, secrets, network, Docker hardening, safeguards design |
| **SECURITY.md** | Phase 1 audit report, security gaps, immediate risks, Phase 5 summary, security checklist |
| **COST_MODEL.md** | Instance type, CPU/memory limits, logging, autoscaling, estimated monthly cost |
| **DEPLOYMENT.md** | This file: folder structure, docker-compose.openclaw.yml, systemd, .env.lab template, token scope, path-guard spec, deployment steps |
