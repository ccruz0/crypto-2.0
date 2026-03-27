# EC2 Instance Mapping & Documentation Consistency Audit

**Date:** 2026-03-04  
**Scope:** Instance identification (OpenClaw/CLO vs Trading PROD), docs/code/docker/nginx consistency, minimal fixes.

---

## A) Instance mapping table

| Instance name (AWS Console) | Expected purpose | Domain/URL | Ports / services | How to verify on the machine |
|----------------------------|------------------|------------|------------------|------------------------------|
| **atp-rebuild-2026** | **Prod ATP** — Dashboard, backend, nginx, trading, Telegram | https://dashboard.hilovivo.com | nginx 80/443, frontend 127.0.0.1:3000, backend 127.0.0.1:8002, Postgres (internal), market-updater, observability | `cd /home/ubuntu/crypto-2.0 && docker compose --profile aws ps`; `ss -tlnp \| grep -E '3000|8002'`; `curl -s http://127.0.0.1:8002/ping_fast`; `sudo nginx -T \| grep -A2 server_name` |
| **atp-lab-ssm-clean** | **Lab OpenClaw (CLO)** — OpenClaw only; no production secrets | None (no public URL) | OpenClaw container 8080 (or 127.0.0.1:8080) | `cd /home/ubuntu/crypto-2.0 && docker compose -f docker-compose.openclaw.yml ps`; `ss -tlnp \| grep 8080`; `curl -sI http://127.0.0.1:8080/` |
| **atp-lab-openclaw** | **Optional LAB** — Same role as atp-lab-ssm-clean if created per RUNBOOK_ARCH_B | None | Same as atp-lab-ssm-clean | Same as above |
| **crypto 2.0** | **Ignored** — Do not use for PROD or scripts | — | — | N/A |

**Instance IDs (canonical):**

| Role | Instance name | Instance ID | Public IP (variable) |
|------|----------------|-------------|----------------------|
| PROD | atp-rebuild-2026 | i-087953603011543c5 | Use dashboard.hilovivo.com or EC2 console; docs conflict (52.220.32.147 vs 52.77.216.100) |
| LAB | atp-lab-ssm-clean | i-0d82c172235770a0d | None (or private only per architecture) |

**Note:** EC2 public IPs change on stop/start unless an Elastic IP is used. Prefer **dashboard.hilovivo.com** (or EC2 console “Public IPv4”) as source of truth; Crypto.com whitelist and SSH should use the **current** PROD IP.

---

## B) Architecture summary

- **Networking and nginx (Dashboard host = PROD):**
  - `/` → frontend (127.0.0.1:3000)
  - `/api` and `/api/*` → backend (127.0.0.1:8002)
  - `/openclaw` → 301 to `/openclaw/`
  - `/openclaw/` → proxy to OpenClaw upstream (today: `http://52.77.216.100:8080/` — LAB’s IP when it had one; target state: LAB private IP, e.g. `http://172.31.3.214:8080/`)
  - `/api/health` → backend `__ping`; `/health` → backend `/health`; `/docs/monitoring/*` → backend reports

- **Docker Compose profiles:**
  - **local:** db, backend-dev or backend, frontend, market-updater (ports 3000, 8002); for development only.
  - **aws:** db, backend-aws (127.0.0.1:8002), frontend-aws (127.0.0.1:3000), market-updater-aws, observability stack; used on PROD only.

- **What runs where:**
  - **PROD (atp-rebuild-2026):** Full ATP stack (nginx, frontend, backend, db, market-updater, observability); nginx proxies `/openclaw/` to LAB (or configured upstream).
  - **LAB (atp-lab-ssm-clean):** OpenClaw only (`docker-compose.openclaw.yml`); no ATP stack, no production secrets.

- **Secrets:**
  - **PROD:** `secrets/runtime.env` (from SSM or rendered by `scripts/aws/render_runtime_env.sh`), `secrets/telegram_key`, `.env.aws`; backend mounts `secrets/runtime.env` and `secrets/telegram_key`.
  - **LAB:** `.env.lab`, token at `/home/ubuntu/secrets/openclaw_token` (not in repo).
  - **Ignored in repo:** `secrets/*` (except examples), `.env`, `.env.aws`, `.env.lab`, `.telegram_key`; `runtime-history/` and `backend/.venv` should not be committed (see C).

---

## C) Inconsistencies

1. **PROD public IP conflict**
   - **AWS_PROD_QUICK_REFERENCE.md**, **PROD_STATUS_UPDATE.md**, **CURSOR_SSH_AWS.md**, **AWS_CRYPTO_COM_CONNECTION.md**, **RUNBOOK_ORDER_HISTORY_ISOLATION.md**, **deploy_openclaw_nginx_prod.sh**: PROD = **52.220.32.147**.
   - **AWS_STATE_AUDIT.md** (table), **RUNBOOK_ARCH_B_PROD_LAB.md**, **AWS_LIVE_AUDIT.md**, **EGRESS_A1_VALIDATION_EVIDENCE.md**: PROD = **52.77.216.100**.
   - **Risk:** SSH/whitelist/docs point at wrong IP if instance was recreated or IP changed. **Fix:** Treat “current PROD IP” as variable; prefer dashboard.hilovivo.com / EC2 console; in one canonical doc (e.g. AWS_PROD_QUICK_REFERENCE) add a note that PROD public IP may change and to confirm in EC2 console.

2. **OpenClaw upstream IP vs LAB “no public IP”**
   - **nginx/dashboard.conf** and **scripts/openclaw/openclaw_nginx_block.txt**: now use `proxy_pass http://172.31.3.214:8080/` (LAB private IP). Live server may still have old IP until runbook is applied.
   - **AWS_PROD_QUICK_REFERENCE.md**, **AWS_LIVE_AUDIT.md**: LAB has **no** public IP.
   - **Risk:** If LAB truly has no public IP, `/openclaw/` will 504. **Fix:** Document that 52.77.216.100 is the LAB (OpenClaw) host when it has a public IP; for VPC-only, use LAB private IP (e.g. 172.31.3.214) in nginx and ensure PROD→LAB security group allows 8080.

3. **atp-lab-openclaw vs atp-lab-ssm-clean**
   - **LAB_BOOTSTRAP_EVIDENCE.md**, **RUNBOOK_ARCH_B_PROD_LAB.md**: reference **atp-lab-openclaw** (new LAB instance to create).
   - Rest of repo uses **atp-lab-ssm-clean** (i-0d82c172235770a0d) as the LAB/OpenClaw host.
   - **Risk:** Confusion which instance is LAB. **Fix:** In audit/runbooks, state clearly: “Current LAB = atp-lab-ssm-clean; atp-lab-openclaw is an optional name when creating a new LAB per RUNBOOK_ARCH_B.”

4. **.gitignore: backend/.venv and runtime-history**
   - Root **.gitignore** has `venv/` and `ENV/` but not **`.venv`** or **`runtime-history/`**.
   - **Risk:** `backend/.venv` or `runtime-history/` could be committed. **Fix:** Add `.venv/` and `runtime-history/` to `.gitignore`.

5. **openapi.json — not available in PROD**
   - In production, `/openapi.json` hits Next.js and returns HTML 404; `/api/openapi.json` hits FastAPI and returns JSON 404. OpenAPI is effectively disabled or not mounted in PROD. **Do not rely on OpenAPI for audits;** use live routes and responses instead (see docs/openclaw/OPEN_OPENCLAW_AND_AUDIT_NOW.md).

6. **API path naming**
   - Backend routes are under prefix **/api** (e.g. `/api/orders/open`, `/api/orders/history`). Nginx proxies `location /api` to `http://localhost:8002/api`. Frontend and docs use `/api/orders/open`, `/api/orders/history`. **Conclusion:** No endpoint name mismatch.

---

## D) Minimal patch plan

### 1) Single source of truth for PROD IP (docs only)

**File:** `docs/aws/AWS_PROD_QUICK_REFERENCE.md`

Add after the Instances table (after line 13):

```diff
 || LAB   | atp-lab-ssm-clean  | i-0d82c172235770a0d  | None           | Online         |
 +
 +**Note:** PROD public IP can change on instance stop/start. Prefer **dashboard.hilovivo.com** or check **EC2 Console → Instances → atp-rebuild-2026 → Public IPv4** for current value. Use that IP for SSH and Crypto.com API whitelist.
```

### 2) Document OpenClaw upstream in nginx

**File:** `nginx/dashboard.conf`

Add a short comment above the OpenClaw proxy_pass (line 70):

```diff
     # OpenClaw Web UI (LAB) – proxy to LAB instance; optional basic auth; allow iframe from dashboard only
     location ^~ /openclaw/ {
-        # Upstream: LAB OpenClaw UI. To change host/port, edit the line below and reload nginx.
+        # Upstream: LAB OpenClaw UI. Use LAB private IP (e.g. 172.31.3.214) when in same VPC; or LAB public IP if assigned. Reload nginx after edit.
         proxy_pass http://52.77.216.100:8080/;
```

### 3) .gitignore: add .venv and runtime-history

**File:** `.gitignore`

Add after the existing `venv/` / virtualenv block (e.g. after line 91):

```diff
 venv/
 wheels/
+.venv/
+runtime-history/
 yarn-debug.log*
```

### 4) Clarify LAB instance name in audit

**File:** `docs/audit/AWS_STATE_AUDIT.md`

In “OpenClaw y LAB” (or inventory) add one line:

```diff
 - **Estado en AWS:** No se sabe desde el repo si en atp-lab-ssm-clean está desplegado OpenClaw; la auditoría viva solo confirma que no hay stack ATP (no comprueba contenedor OpenClaw).
 + **Nombre LAB actual:** atp-lab-ssm-clean (i-0d82c172235770a0d). RUNBOOK_ARCH_B opcionalmente crea una instancia llamada atp-lab-openclaw; en ese caso sería la instancia LAB en lugar de atp-lab-ssm-clean.
```

---

## E) Verification checklist (exact commands)

**On PROD (atp-rebuild-2026) — via SSM or SSH:**

```bash
cd /home/ubuntu/crypto-2.0
docker compose --profile aws ps
ss -tlnp | grep -E '3000|8002'
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/ping_fast
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/
sudo nginx -t
sudo grep -E "server_name|proxy_pass" /etc/nginx/sites-enabled/* 2>/dev/null | head -30
curl -sI https://dashboard.hilovivo.com/openclaw/ | head -5
```

**On LAB (atp-lab-ssm-clean) — via SSM:**

```bash
cd /home/ubuntu/crypto-2.0
docker compose -f docker-compose.openclaw.yml ps
ss -tlnp | grep 8080
curl -sI http://127.0.0.1:8080/ | head -5
```

**From your laptop (no SSH):**

```bash
curl -sI https://dashboard.hilovivo.com/api/health | head -5
./scripts/openclaw/run_openclaw_check_via_ssm.sh
```

---

**References:** docs/aws/AWS_PROD_QUICK_REFERENCE.md, docs/openclaw/README.md, docs/openclaw/ARCHITECTURE_V1_1_INTERNAL_SERVICE.md, nginx/dashboard.conf, docker-compose.yml, docker-compose.openclaw.yml.
