# Security Incident Response – Docker RCE & docker.sock Exposure

**Classification:** Confidential – Post-incident audit  
**Date:** 2025-02-20  
**Context:** Confirmed container compromise in production (AWS EC2). Frontend container executed malicious commands (`wget` + `base64 ... | bash`). Backend mounts `/var/run/docker.sock`, enabling full host compromise.

---

## SECTION 1: Confirmed Architectural Weakness

### 1.1 docker.sock mount (CRITICAL)

- **Location:** `docker-compose.yml` line 275, service `backend-aws`
- **Config:** `- /var/run/docker.sock:/var/run/docker.sock`
- **Purpose in repo:** Used only for **tail_logs** in `backend/app/services/ai_engine/tools.py` – runs `docker compose logs --tail N <service>` for AI engine diagnostics. Allowlist: `backend-aws`, `db`, `frontend-aws`, `market-updater-aws`.
- **Risk:** Any RCE or SSRF in the backend (or any process with access to the socket) can control the Docker daemon and achieve host takeover. With frontend already compromised, pivot to backend (e.g. via unauthenticated endpoints) makes this a direct path to host.

### 1.2 Unauthenticated high-impact API endpoints

| Endpoint | Auth | Risk |
|----------|------|------|
| `POST /api/monitoring/backend/restart` | **None** | Triggers `subprocess.run(["bash", restart_script])` or `systemctl`/`supervisorctl`. In container the script is absent so it no-ops; if script existed or ran on host, arbitrary execution. |
| `POST /api/monitoring/workflows/{workflow_id}/run` | **None** | Runs fixed-path Python script for `watchlist_consistency` via `subprocess.run([sys.executable, script_path])`. No arbitrary args but DoS and abuse vector. |
| `POST /api/ai/run` | **None** | Can pass `tool_calls` including `tail_logs`; requires docker.sock. Without socket, fails gracefully. |

### 1.3 Frontend container attack surface

- **Next.js:** No custom API routes under `/pages/api` or `/app/api`. All `/api/*` are **rewrites** to backend (`next.config.ts` → `BACKEND_URL`). So API logic runs in **backend**, not frontend.
- **Production frontend image:** `frontend/Dockerfile` uses `node:22-alpine` and **HEALTHCHECK** uses `wget` (line 46). So **wget is present in the runtime image**, which matches the observed attacker use of `wget http://.../logic.sh`.
- **Dev Dockerfile:** `Dockerfile.dev` explicitly installs `wget` (`apk add ... wget`). Not used in AWS profile but confirms intent to have wget in frontend.
- **Conclusion:** Frontend container had **wget** available; RCE likely via **supply-chain (npm)** or **Next.js/dependency vulnerability**, not a custom app route. No evidence in repo of eval/dynamic code execution in frontend code.

### 1.4 Backend subprocess usage (allowed but must be locked down)

- **routes_monitoring.py:** `restart_backend()` → bash script or systemctl/supervisorctl. **run_workflow("watchlist_consistency")** → `subprocess.run([sys.executable, script_path])`.
- **scheduler.py:** Nightly consistency → `subprocess.run([sys.executable, watchlist_consistency_check.py])`.
- **ai_engine/tools.py:** `search_repo` (rg/grep), `read_snippet` (file read), **tail_logs** (docker compose logs). All use allowlists; tail_logs requires docker.sock.
- **scripts (dev/ops only):** Various `subprocess`/`shell=True` in `detect_telegram_senders.py`, `debug_strategy.py`, `assert_no_blocked_alert_regressions.py`, etc. Not in request path.

---

## SECTION 2: Likely Entry Point

- **Primary hypothesis:** **Frontend container RCE via supply chain or dependency** (compromised npm package or Next.js/server dependency). No custom API routes in frontend that execute code; rewrites only proxy to backend.
- **Alternative:** Exploit in Next.js server (SSR/rewrites) or in a dependency that runs at request time. Recommend dependency audit and lockfile review.
- **Pivot to host:** Once in frontend, attacker had wget and could run scripts. With **backend mounting docker.sock**, if attacker could reach backend (e.g. unauthenticated restart or internal network), they could use Docker from backend to escape to host. So **unauthenticated restart + docker.sock** is a plausible escalation path even if restart script itself no-ops in container.

---

## SECTION 3: Required Immediate Fixes

1. **Remove docker.sock mount** from `backend-aws` in `docker-compose.yml`.
2. **Remove Docker CLI and docker-compose-plugin** from backend production image (`Dockerfile.aws`) so tail_logs fails cleanly without socket.
3. **Require diagnostics auth** for `POST /api/monitoring/backend/restart` and `POST /api/monitoring/workflows/{workflow_id}/run` (same as other diagnostics: `ENABLE_DIAGNOSTICS_ENDPOINTS=1` + `X-Diagnostics-Key`).
4. **Frontend production image:** Remove wget from runtime (use Python or node for healthcheck, or minimal probe without wget).
5. **Harden backend-aws:** `read_only: true` where possible, `security_opt: no-new-privileges`, drop `NET_RAW`; ensure non-root user (already appuser in Dockerfile.aws).
6. **group_add: "0"** in backend-aws: remove if only used for docker socket access; otherwise document and restrict.

---

## SECTION 4: Exact Code Patches (diff format)

### 4.1 docker-compose.yml (backend-aws)

```diff
     volumes:
       - ./docker-compose.yml:/app/docker-compose.yml:ro
-      - /var/run/docker.sock:/var/run/docker.sock
+      # SECURITY: docker.sock REMOVED - was used only for tail_logs; enables host takeover if backend compromised.
       - ./backend/ai_runs:/app/backend/ai_runs
       - aws_trading_config_data:/data
-    group_add:
-      - "0"
+    security_opt:
+      - no-new-privileges:true
+    cap_drop:
+      - ALL
     working_dir: /app
```

### 4.2 frontend Dockerfile (production) – HEALTHCHECK without wget

```diff
-HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -qO- http://localhost:3000/ || exit 1
+# SECURITY: No wget in runtime - use node to avoid RCE payloads that rely on wget/curl
+HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD node -e "require('http').get('http://127.0.0.1:3000/', (r)=>{ process.exit(r.statusCode===200?0:1); }).on('error', ()=>process.exit(1));" || exit 1
```

### 4.3 backend Dockerfile.aws – remove Docker CLI from runner

```diff
-# Docker CLI + compose plugin for tail_logs (docker compose ...) inside container.
-RUN apt-get update && apt-get install -y --no-install-recommends \
-      ca-certificates curl gnupg \
-    && install -m 0755 -d /etc/apt/keyrings \
-    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
-    && ... docker-ce-cli docker-compose-plugin ...
+# SECURITY: Docker CLI and docker-compose-plugin REMOVED. tail_logs will return "docker not available".
+RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
+    && apt-get clean && rm -rf /var/lib/apt/lists/*
```

### 4.4 backend routes_monitoring.py – auth for restart and workflow run

```diff
-@router.post("/monitoring/backend/restart")
-async def restart_backend():
+@router.post("/monitoring/backend/restart")
+async def restart_backend(request: Request):
+    _verify_diagnostics_auth(request)
     ...

-@router.post("/monitoring/workflows/{workflow_id}/run")
-async def run_workflow(workflow_id: str, db: Session = Depends(get_db)):
+@router.post("/monitoring/workflows/{workflow_id}/run")
+async def run_workflow(workflow_id: str, request: Request, db: Session = Depends(get_db)):
+    _verify_diagnostics_auth(request)
     ...
```

### 4.5 New file: .dockerignore (repo root)

Used when building with context `.` (e.g. `docker build -f backend/Dockerfile.aws .`). Excludes `.env`, `secrets/`, `frontend/node_modules`, etc., from build context.

---

## SECTION 5: Hardened Final Compose + Dockerfiles

(See applied patches in repo: `docker-compose.yml`, `frontend/Dockerfile`, `backend/Dockerfile.aws`.)

Summary of hardening:

- **backend-aws:** No docker.sock; no Docker CLI in image; security_opt no-new-privileges; cap_drop ALL; read_only filesystem with tmpfs for /tmp if needed; remove group_add "0" unless required for other reasons.
- **frontend-aws:** No wget in production image; healthcheck without wget; security_opt and cap_drop already present; read_only already set.
- **.dockerignore:** Already present for frontend and backend; ensure no .env or secrets in build context.

---

## SECTION 6: Clean Redeploy Plan

1. **Terminate compromised EC2 instance.** Do not reuse.
2. **Launch new instance** from a clean, up-to-date AMI (e.g. latest Amazon Linux 2 or Ubuntu 22.04).
3. **Harden host:** Minimal install; no unnecessary packages; egress firewall (only required IPs/domains); block 91.92.243.113, 78.153.140.16 and any other known-bad IPs.
4. **Install Docker** from official repo; do not mount docker.sock into application containers.
5. **Rotate all secrets** (see Section 7 below): DB password, Telegram tokens, Crypto.com API keys, DIAGNOSTICS_API_KEY, ADMIN_ACTIONS_KEY, SECRET_KEY, OPENAI if used.
6. **Clone repo** from trusted source (tag or commit after security patches); do not copy files from old instance.
7. **Build images** with patched Dockerfiles and compose (no docker.sock, no wget in frontend, no Docker CLI in backend).
8. **Deploy** with `docker compose --profile aws up -d` using rotated secrets only.
9. **Verify:**  
   - `docker inspect backend-aws` shows no bind mount for `/var/run/docker.sock`.  
   - No egress to attacker IPs (test with curl/wget from container if needed, then remove tools).  
   - Diagnostics endpoints return 404 without valid X-Diagnostics-Key.
10. **Re-enable cron/systemd** only for necessary tasks (e.g. backups); avoid generic restart scripts that call Docker from host.

---

## SECTION 7: Long-Term Hardening Plan

- **Secrets:** Store in AWS Secrets Manager or Parameter Store; inject at runtime; never in image or compose env files in repo. Rotate after incident (see Secret Rotation Checklist below).
- **Network:** Egress filtering at host/security group so containers only reach required endpoints (e.g. api.crypto.com, Telegram, DB).
- **Auth:** All operational endpoints (restart, workflow run, diagnostics, AI run) behind single strong auth (e.g. DIAGNOSTICS_API_KEY / ADMIN_ACTIONS_KEY) and only when ENABLE_DIAGNOSTICS_ENDPOINTS=1.
- **Container restart:** Do not mount docker.sock. Use host-side job (cron/systemd) that runs `docker compose restart backend-aws` on the host, or use ECS/ECS Exec if migrating to ECS.
- **tail_logs:** Keep disabled in production (no docker.sock). For log access, use centralized logging (e.g. CloudWatch, Fluent Bit) or read-only log volume mounts from host.
- **Supply chain:** Audit frontend dependencies (`npm audit`, lockfile); consider allowlist for npm packages; monitor for Next.js/server CVEs.
- **Seccomp/AppArmor:** Use default seccomp profile (`security_opt: no-new-privileges` already set). For stricter containment, add a custom seccomp profile that blocks `unshare`, `mount`, `ptrace`, and other unneeded syscalls. Document in runbook.
- **Outbound firewall:** On the EC2 host or security group, restrict egress to only required endpoints: API (api.crypto.com), Telegram (api.telegram.org), package repos for updates, and optionally CloudWatch. Block all other outbound by default; explicitly allow known-good IPs/domains.

---

## Secret Rotation Checklist (post-incident)

| Secret | Where used | Risk level | Action |
|--------|------------|------------|--------|
| POSTGRES_PASSWORD / DATABASE_URL | db, backend, market-updater | Critical | Rotate immediately; update all env and redeploy. |
| TELEGRAM_BOT_TOKEN* / TELEGRAM_CHAT_ID* | backend, market-updater, telegram-alerts | High | Rotate bot token; revoke old token in BotFather. |
| EXCHANGE_CUSTOM_API_KEY / EXCHANGE_CUSTOM_API_SECRET | backend (Crypto.com) | Critical | Rotate API key on exchange; update env. |
| CRYPTO_PROXY_TOKEN | backend (if proxy used) | High | Rotate if in use. |
| SECRET_KEY | backend (sessions/signing) | High | Rotate; invalidates existing sessions. |
| DIAGNOSTICS_API_KEY / ADMIN_ACTIONS_KEY | backend (diagnostics/admin) | High | Rotate; update scripts/tools that call diagnostics. |
| OPENAI_API_KEY | If used in ai_engine | High | Rotate if present. |
| API_KEY (demo-key) | Backend API key auth | Medium | Change if used for any real auth. |

---

## Attack Surface Summary

- **Dangerous execution paths:** restart_backend (bash/systemctl), run_workflow (Python script), tail_logs (docker compose), scheduler nightly (Python script). All must be behind auth and/or removed from production (docker.sock).
- **Routes that could trigger command execution:** POST `/api/monitoring/backend/restart`, POST `/api/monitoring/workflows/watchlist_consistency/run`, POST `/api/ai/run` (tool_calls → tail_logs). First two had no auth; third has no auth but tool_calls are allowlisted.
- **No endpoint in repo exposes arbitrary Docker control** (e.g. docker run/exec) except that with docker.sock mounted, any backend RCE would imply Docker control.

---

*End of audit. Apply patches in SECTION 4 and SECTION 5, then follow SECTION 6 for clean redeploy.*
