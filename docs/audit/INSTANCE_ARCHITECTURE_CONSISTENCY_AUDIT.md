# Instance + Architecture Consistency Audit

**Date:** 2026-03-04  
**Scope:** docs, scripts, nginx, docker-compose, secrets vs deployed state. PROD → LAB over private IP is live.

---

## 1. Source of truth: instances

| Role | Instance name | Instance ID | Private IP | Public IP | What runs | Verify |
|------|---------------|-------------|------------|-----------|-----------|--------|
| **PROD** | atp-rebuild-2026 | i-087953603011543c5 | 172.31.32.169 | 52.220.32.147 | nginx, frontend :3000, backend :8002, db, market-updater, observability; proxies /openclaw/ to LAB | `docker compose --profile aws ps`; `curl -sI http://127.0.0.1:8002/ping_fast` |
| **LAB** | atp-lab-ssm-clean | i-0d82c172235770a0d | 172.31.3.214 | (variable/none) | OpenClaw only on 8080 | `docker compose -f docker-compose.openclaw.yml ps`; `curl -sI http://127.0.0.1:8080/` |
| atp-lab-openclaw | optional LAB | i-090a1b69a56d2adbe | — | — | Keep **stopped**; current LAB = atp-lab-ssm-clean | N/A |
| crypto 2.0 | ignored | i-08726dc37133b2454 | — | — | Do not use for PROD | N/A |

**Canonical access:** https://dashboard.hilovivo.com (PROD). OpenClaw UI: https://dashboard.hilovivo.com/openclaw/ (Basic Auth, proxy to LAB 172.31.3.214:8080).

---

## 2. References to old OpenClaw upstream IP (52.77.216.100)

**Target state:** All OpenClaw proxy/config must use LAB private IP **172.31.3.214:8080**. Live PROD nginx was fixed; repo and docs still contain the old IP in the following places.

| File | Line(s) | Content / risk |
|------|---------|----------------|
| docs/openclaw/OPENCLAW_PRIVATE_NETWORK_MIGRATION.md | 9, 99, 203, 215 | Example/current text and proxy_pass using 52.77.216.100 |
| docs/audit/AWS_STATE_AUDIT.md | 28 | PROD table shows public IP 52.77.216.100 (conflicts with 52.220.32.147) |
| scripts/openclaw/fix_openclaw_proxy_prod.sh | 5 | OLD=52.77.216.100 (intentional: string to replace on server) — **keep** |
| docs/openclaw/OPENCLAW_UI_IN_DASHBOARD.md | 33, 35, 141, 165 | Example proxy_pass and curl to 52.77.216.100 |
| docs/openclaw/DEPLOY_OPENCLAW_NGINX_PROD.md | 62 | Example proxy_pass 52.77.216.100 |
| docs/aws/AWS_BRINGUP_RUNBOOK.md | 648, 652, 665 | Example “current instance Public IPv4” 52.77.216.100 |
| docs/audit/EC2_OPENCLAW_INSTANCE_AND_CONSISTENCY_AUDIT.md | 21, 34, 56, 62, 106 | Conflict note and old proxy example |
| docs/audit/RUNBOOK_ARCH_B_PROD_LAB.md | 16 | PROD public IP 52.77.216.100 in table |
| docs/audit/EGRESS_A1_VALIDATION_EVIDENCE.md | 3 | Instance example 52.77.216.100 |
| docs/runbooks/NGINX_OPENCLAW_PROXY_TO_LAB_PRIVATE_IP.md | 11, 15, 50 | Documents “old public IP 52.77.216.100” and replacement — **keep as doc** |
| docs/audit/RUNBOOK_EGRESS_OPTION_A1.md | 1, 118, 288 | Example instance IP 52.77.216.100 |
| docs/aws/AWS_LIVE_AUDIT.md | 25, 154 | PROD public IP 52.77.216.100 in table and text |
| docs/openclaw/OPENCLAW_504_UPSTREAM_DIAGNOSIS.md | 69, 129 | proxy_pass and 504 diagnosis referring to 52.77.216.100 |

---

## 3. Nginx routing expectations (PROD)

**Server:** dashboard.hilovivo.com (listen 443 ssl). File: `/etc/nginx/sites-enabled/default` (or repo source `nginx/dashboard.conf`).

| Path | Upstream | Bind |
|------|----------|------|
| `/` | frontend | http://localhost:3000 |
| `/api` | backend | http://localhost:8002/api |
| `/api/health` | backend __ping | http://localhost:8002/__ping |
| `/api/monitoring/` | backend | http://localhost:8002/api/monitoring/ |
| `/openclaw` | redirect | return 301 /openclaw/ |
| `/openclaw/` | OpenClaw (LAB) | **http://172.31.3.214:8080/** |
| `/health` | backend | http://localhost:8002/health |
| `/docs/monitoring/*` | backend | http://localhost:8002 |

**Expected OpenClaw block (snippet):**

```nginx
location = /openclaw { return 301 /openclaw/; }
location ^~ /openclaw/ {
    proxy_pass http://172.31.3.214:8080/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_cache_bypass $http_upgrade;
    auth_basic "OpenClaw";
    auth_basic_user_file /etc/nginx/.htpasswd_openclaw;
    # ... timeouts, CSP frame-ancestors, etc.
}
```

---

## 4. Docker Compose expectations

| File | Profile | Where | Ports (host) | Notes |
|------|---------|-------|---------------|------|
| docker-compose.yml | **aws** | PROD only | frontend-aws 127.0.0.1:3000, backend-aws 127.0.0.1:8002, db (no host port), observability 127.0.0.1 | Never bind backend/frontend to 0.0.0.0 on PROD |
| docker-compose.yml | local | dev only | 3000, 8002 | Not for PROD |
| docker-compose.openclaw.yml | — | LAB only | openclaw 8080 (0.0.0.0:8080 in container) | No production secrets; token via file mount |

**Ports that must not be public on PROD:** 8002 (backend), 3000 (frontend), 5432 (db). Only nginx (80/443) and SSH (if enabled) should be open to the internet.

---

## 5. Secrets handling

**Ignored in repo (.gitignore):** `secrets/*` (except `.gitkeep`, `runtime.env.example`), `.env`, `.env.aws`, `.env.lab`, `.telegram_key`, `.openclaw_pat`, `.venv/`, `runtime-history/`.

**PROD:** Secrets live in `secrets/runtime.env`, `secrets/telegram_key` (and optionally `.env.aws`). Injected by deploy (e.g. SSM or render_runtime_env.sh). Backend mounts `secrets/runtime.env` and `secrets/telegram_key`.

**LAB:** `.env.lab` (ignored); OpenClaw token at `/home/ubuntu/secrets/openclaw_token` (not in repo).

**Risks:** Any doc or script that tells users to commit or paste `.telegram_key`, `secrets/runtime.env`, or token values into the repo. Audit: no script in repo writes secrets into tracked paths; docs should state “never commit secrets”.

---

## 6. Actionable remediation plan

### P0 (canonical source of truth)

- **Create/update** `docs/runbooks/INSTANCE_SOURCE_OF_TRUTH.md` with the definitive instance table (private/public IPs, IDs, what runs where). **Done** (see that file).
- **Single PROD public IP in docs:** Decide canonical value (e.g. 52.220.32.147 as of 2026-03-04) and add a note in `docs/aws/AWS_PROD_QUICK_REFERENCE.md`: “PROD public IP may change; prefer dashboard.hilovivo.com or EC2 console.” **Already present.**

### P1 (doc consistency – no code change)

- **Replace or annotate old IP in docs:** In every file listed in §2 (except `fix_openclaw_proxy_prod.sh` and runbook “old IP” explanation), either:
  - Replace example `52.77.216.100` with `172.31.3.214` for OpenClaw upstream, or
  - Add one line: “Use LAB private IP 172.31.3.214; 52.77.216.100 is deprecated.”
- **PROD public IP:** In `AWS_STATE_AUDIT.md`, `RUNBOOK_ARCH_B_PROD_LAB.md`, `AWS_LIVE_AUDIT.md`, `EGRESS_A1_VALIDATION_EVIDENCE.md`, `RUNBOOK_EGRESS_OPTION_A1.md`: state that PROD public IP is variable and point to AWS_PROD_QUICK_REFERENCE or EC2 console.

### P2 (optional hardening)

- **OpenClaw docs:** In `OPENCLAW_UI_IN_DASHBOARD.md`, `DEPLOY_OPENCLAW_NGINX_PROD.md`, `OPENCLAW_PRIVATE_NETWORK_MIGRATION.md`, `OPENCLAW_504_UPSTREAM_DIAGNOSIS.md`: use 172.31.3.214 in all examples and curl commands.
- **.gitignore:** Already includes `.venv/`, `runtime-history/`, `.telegram_key`. No change needed.

### Verification commands (after any doc/config change)

**On PROD:**

```bash
curl -sS -m 5 -I http://172.31.3.214:8080/ | head -5   # expect 200
curl -sS -m 8 -I https://dashboard.hilovivo.com/openclaw/ | head -10   # expect 401
sudo nginx -t
```

**From repo (no secrets):**

```bash
grep -Rn "52\.77\.216\.100" --include="*.conf" --include="*.yml" --include="*.txt" . 2>/dev/null | grep -v ".bak" || true
# Should show only fix_openclaw_proxy_prod.sh (OLD=) and runbook “old IP” text.
```

---

**Do not:** Change production secrets, broaden AWS security groups, or refactor beyond the minimal diffs above.
