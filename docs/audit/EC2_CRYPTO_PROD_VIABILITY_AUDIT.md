# EC2 "Crypto" Instance — PROD vs LAB Viability Audit

**Date:** 2026-02-20  
**Scope:** Repository + deployment logic + security and reproducibility for dual-environment (PROD / LAB)  
**Constraints:** Docker Compose only, minimal structural change, patch-style where possible.

---

## 1. Current Risk Summary

| Category | Severity | Finding |
|----------|----------|--------|
| **Secrets** | High | `.env.aws` was previously tracked (removed in 66b72a3); git history may still contain old secrets. `.env.aws` and backups (`.env.aws.bak*`) must never be committed. |
| **Secrets in code** | High | `backend/app/api/routes_internal.py` logs `repr(API_KEY)` and API key length on `/internal/crypto/ping-private` — **full API key can appear in logs**. |
| **Secrets in scripts** | Critical | `backend/scripts/verify_credentials.py` prints `repr(api_key)`, `repr(api_secret[:20])`, `repr(api_secret[-20:])`, and leading/trailing 5 chars of secret — **exposes full credentials** if run with prod env. |
| **Env contamination** | Medium | `frontend-aws` loads `.env.local` (compose line 448). On server, if `.env.local` exists, local Telegram/dev tokens can leak into PROD build or runtime. |
| **Port exposure (repo)** | Low | Repo is correct: backend-aws `127.0.0.1:8002`, frontend-aws `127.0.0.1:3000`, db has **no** port mapping. Deploy gate `scripts/aws/verify_no_public_ports.sh` enforces this. |
| **Port exposure (server)** | Medium | Past audit (AUDIT_AWS.md) reported `0.0.0.0:8002`, `0.0.0.0:3000`, and `0.0.0.0:5432` on the instance — may be from older compose or overrides; must be re-verified on live server. |
| **Unknown service** | Medium | Port 9000 (Python proxy) noted in AUDIT_AWS.md — purpose unclear; should be identified and either documented or removed for PROD. |
| **Hardcoded IPs/hostnames** | Low | Scripts and frontend reference `47.130.143.159`, `54.254.150.31`, `hilovivo-aws` in docs and fallbacks. Prefer env (e.g. `EC2_HOST`) or DNS. |
| **TLS** | OK | Nginx `dashboard.conf` uses Let's Encrypt, TLS 1.2/1.3, HSTS. HTTP→HTTPS redirect. |
| **Reverse proxy** | OK | Nginx on host (80/443) → localhost:3000 (frontend), localhost:8002 (API). Not in Docker; documented in `setup_nginx_aws.sh` and `deploy_report_endpoints.sh`. |

---

## 2. Exposure Analysis

### 2.1 Docker Compose port bindings (from repo)

| Service | Binding | Notes |
|---------|--------|--------|
| db | *(none)* | Internal only; backend uses `db:5432`. |
| backend-dev / backend (local) | `8002:8002` | Dev only; not used with `--profile aws`. |
| backend-aws | `127.0.0.1:8002:8002` | Correct for PROD — nginx only. |
| backend-aws-canary | `127.0.0.1:8003:8002` | Loopback only. |
| frontend (local) | `3000:3000` | Dev only. |
| frontend-aws | `127.0.0.1:3000:3000` | Correct for PROD. |
| prometheus, grafana, alertmanager, node-exporter, cadvisor | `127.0.0.1:*` | Observability internal only. |

No app ports (3000, 8000, 8002) are bound to `0.0.0.0` in the **aws** profile. Local profile intentionally binds for dev.

### 2.2 Reverse proxy

- **Present:** Nginx on host (systemd), not in Docker.
- **Config:** `nginx/dashboard.conf` — HTTP→HTTPS, proxy to `localhost:3000` and `localhost:8002`.
- **Deployment:** `setup_nginx_aws.sh`, `deploy_report_endpoints.sh` (scp + SSH to install/reload). Nginx config is in repo; certs (e.g. certbot) are server-side.

### 2.3 Direct app port exposure

- **Intended:** All public traffic via 80/443 → Nginx → 3000/8002. Backend/frontend bound to 127.0.0.1.
- **Risk:** If the running server was ever started with an older compose or override that published 8002/3000/5432 to 0.0.0.0, those would be exposed. **Action:** On the Crypto instance, run `ss -lntp | grep -E '8002|3000|5432'` and confirm only 127.0.0.1 (or no 5432). If 0.0.0.0 is found, redeploy with current compose and no overrides.

---

## 3. Secret Management Analysis

### 3.1 Where secrets live

- **Repo (committed):** None. `.env`, `.env.aws`, `.env.local`, `secrets/*` (except `secrets/.gitkeep`, `secrets/runtime.env.example`) are in `.gitignore`. `runtime.env.example` is a redacted template.
- **Server:** `.env`, `.env.aws`, `secrets/runtime.env` (from `scripts/aws/render_runtime_env.sh`). Optional: AWS SSM for Telegram/admin/diagnostics keys; fallback is `.env.aws`.
- **CI:** GitHub Actions uses `EC2_HOST`, `EC2_KEY`, `PUBLIC_BASE_URL` / `API_BASE_URL` (secrets). No app secrets in workflow file.

### 3.2 Issues

1. **Git history:** `.env.aws` was removed from tracking in 66b72a3; before that it was tracked. If it ever contained real secrets, they may still be in history. Consider `git filter-repo` or BFG to purge and rotate any exposed secrets.
2. **Backend diagnostic logging:** `routes_internal.py` (lines 111–113) logs `repr(API_KEY)` and length. **Fix:** Remove or redact (e.g. log only length and prefix like `API_KEY[:4]...`).
3. **verify_credentials.py:** Prints full key and segments of secret. **Fix:** Only print length, prefix/suffix placeholders (e.g. `***...***`), and presence; never `repr()` of key/secret.
4. **frontend-aws env_file:** Uses `.env.local`. For PROD, **do not** load `.env.local` on the server (or remove it from `env_file` for frontend-aws so PROD build/runtime cannot see local tokens).

### 3.3 What’s good

- `render_runtime_env.sh` uses umask 077 for `secrets/runtime.env`.
- Backend-aws explicitly does **not** load `.env.local` (comment and env_file list).
- Deploy guard `scripts/aws/check_no_inline_secrets_in_compose.sh` prevents inline secrets in compose.
- SSM path for Telegram/admin/diagnostics is documented; fallback to `.env.aws` is explicit.

---

## 4. Reproducibility Assessment

### 4.1 Fully reproducible from repo

- Docker Compose stack (profile `aws`): images built from Dockerfiles in repo; no db port published.
- Nginx config: `nginx/dashboard.conf` and rate-limiting snippet; deployment via scripts.
- Deploy flow: GitHub Actions → rsync → `scripts/deploy_aws.sh` (git reset, render runtime.env, compose up).
- Backend/frontend env: From `.env`, `.env.aws`, `secrets/runtime.env` (and optionally SSM); no hardcoded secrets in compose.

### 4.2 Manual / server-only

- **Nginx install and SSL:** `setup_nginx_aws.sh` or manual certbot; certs live on server (e.g. `/etc/letsencrypt/`). Not in repo.
- **Secrets on server:** `.env.aws` and `secrets/runtime.env` are created on the host (or via SSM); not in git. Document in runbook how to create them for a new instance.
- **Cron/systemd:** AUDIT_AWS.md mentions health monitor, auto-restart, cleanup. If these are required for PROD, they should be documented (and ideally scripted) so a new instance can be reproduced.
- **Port 9000:** Service on 9000 is undocumented; reproducibility is unclear until purpose is known.

### 4.3 State outside Docker volumes

- **Postgres:** `postgres_data` and `aws_postgres_data` volumes — good.
- **Trading config:** `TRADING_CONFIG_PATH=/data/trading_config.json` with volume `aws_trading_config_data` — good.
- **Backend:** Mounts `./backend/ai_runs` and docker socket for tail_logs; `ai_runs` is host path. For a new instance, `ai_runs` would start empty; no critical state there for “replicate from scratch” beyond optional runs.
- **Grafana/Prometheus:** Use named volumes; reproducible.

**Verdict:** Reproducibility is good for “same repo + same env files on a new host”. Gaps: nginx/SSL and cron/systemd documented but not fully automated; port 9000 and server-only config (e.g. backup files) should be cleaned or documented for PROD.

---

## 5. PROD Viability Verdict

**Classification: REQUIRES MODERATE CLEANUP BEFORE PROD**

**Reasoning:**

- **Repo:** Compose and Nginx are PROD-oriented (127.0.0.1 binds, no db port, TLS, rate limiting). Deploy gates (no public ports, no inline secrets) are in place.
- **Instance:** Past audit reported backup files with API keys, possible 0.0.0.0 exposure for 8002/3000/5432, unknown service on 9000, and drift (e.g. 603 uncommitted changes). That makes the **current Crypto instance** “contaminated” until cleaned and re-verified.
- **Code:** Logging/printing of API key and secret in `routes_internal.py` and `verify_credentials.py` must be fixed before treating the environment as hardened PROD.

**Conclusion:** The **same** instance can become PROD after cleanup and the code/config fixes below. A **new** clean PROD instance is not required if you:

1. Clean the server (remove .env*.bak*, confirm no 5432/8002/3000 on 0.0.0.0, document or remove port 9000).
2. Apply the minimal hardening and secret-handling fixes in the repo.
3. Redeploy from a clean git state (e.g. reset to origin/main, no local .env.local for frontend-aws).

If you prefer zero trust on the current host (e.g. too many ad-hoc changes or unknown processes), use the migration path in §7 (new PROD instance) and keep Crypto as LAB.

---

## 6. Hardening Plan (Minimal Diff)

Use this if you treat the Crypto instance as the future PROD host after cleanup.

### 6.1 Code / repo (patch-style)

1. **Stop logging API key in `routes_internal.py`**  
   - File: `backend/app/api/routes_internal.py` (around 109–113).  
   - Remove or replace: do not log `repr(API_KEY)`. Log at most length and a fixed prefix (e.g. first 4 chars) for diagnostics.

2. **Stop printing secrets in `verify_credentials.py`**  
   - File: `backend/scripts/verify_credentials.py`.  
   - Replace any `repr(api_key)` / `repr(api_secret...)` and printing of raw key/secret with: length, “SET”/“NOT SET”, and at most a masked prefix/suffix (e.g. `****...****`).

3. **Avoid loading `.env.local` for frontend-aws (PROD)**  
   - File: `docker-compose.yml`, service `frontend-aws`.  
   - Remove `.env.local` from `env_file` so PROD never sees local dev tokens. Keep `.env` and `.env.aws` only.

4. **Optional:** Replace hardcoded IPs in scripts/docs with `EC2_HOST` or DNS (e.g. `dashboard.hilovivo.com`). Low priority; improves maintainability.

### 6.2 Docker Compose (no structural change)

- No change needed for port bindings (already 127.0.0.1 for backend-aws and frontend-aws).
- Ensure no override file on the server publishes 5432 or 0.0.0.0 for 3000/8002. Deploy must use only repo `docker-compose.yml` (and optional non-secret override if you introduce one later).

### 6.3 Reverse proxy

- Keep Nginx on host; no change to architecture.
- Ensure rate-limiting zones are included in the main nginx config (see `nginx/rate_limiting_zones.conf` and `dashboard.conf` comments).
- After hardening, confirm only 80/443 are open to the internet; 3000/8002 only on 127.0.0.1.

### 6.4 Secret separation

- **PROD:** Use `secrets/runtime.env` (from `render_runtime_env.sh`) with SSM or a server-only `.env.aws`. Never commit `.env.aws` or backups.
- **LAB:** Use a separate `.env.lab` or distinct SSM path so LAB and PROD never share the same Telegram/API keys if you want isolation.
- Rotate any credentials that may have been in git history (Telegram, Exchange API, SECRET_KEY, etc.).

### 6.5 Safe migration steps (Crypto → PROD on same instance)

1. **On workstation:** Apply the code and compose changes above; commit and push.
2. **On Crypto instance:**  
   - Remove any `.env.aws.bak*`, `.env.bak*` and ensure no secrets in world-readable files.  
   - Identify port 9000: `ss -lntp | grep 9000` and process; stop if not needed or move to LAB-only.  
   - Confirm `ss -lntp | grep -E '5432|8002|3000'` shows no 0.0.0.0 for 5432; 8002 and 3000 only on 127.0.0.1 (or fix compose/override and restart).  
   - Ensure `secrets/runtime.env` exists (run `scripts/aws/render_runtime_env.sh`) and that `.env.local` is absent or not used by frontend-aws.  
   - Pull latest, run `scripts/deploy_aws.sh` (or trigger CI).  
   - Verify: `curl -sS http://localhost:8002/api/health/system | jq` and HTTPS in browser.
3. **DNS/firewall:** Point PROD DNS (e.g. dashboard.hilovivo.com) to this instance; restrict SSH (e.g. 22) to known IPs; keep 80/443 open as needed.

---

## 7. Rollback Strategy

- **Git:** `scripts/rollback_aws.sh` (rollback to a specific commit SHA). Ensure rollback commit does not reintroduce 0.0.0.0 or secret logging.
- **Compose:** `docker compose --profile aws down` then `up -d` with previous image tags if you pin them; or redeploy previous commit and re-run `deploy_aws.sh`.
- **Nginx:** Backup before changes: e.g. `cp /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-available/dashboard.conf.bak.<date>`. Restore and `sudo systemctl reload nginx` if needed.
- **Secrets:** Keep a secure copy of `secrets/runtime.env` and `.env.aws` (or SSM) so you can restore env and restart containers without redeploying code.
- **Data:** Postgres in `postgres_data` / `aws_postgres_data`. For rollback of app only, do not destroy volumes. For full instance replacement, use the migration path below (dump/restore).

---

## 8. If You Choose “Do Not Use as PROD” (Migrate to New Instance)

Use this if you decide the Crypto instance remains LAB and a new instance is PROD.

### 8.1 New PROD instance

1. Launch new EC2 (same region/VPC as needed); attach new Elastic IP.
2. Install Docker, Docker Compose, Nginx, certbot (same as current setup or use `setup_nginx_aws.sh`).
3. Clone repo; create `.env`, `.env.aws` (or use SSM), run `render_runtime_env.sh` to create `secrets/runtime.env`. Do **not** copy `.env.local` from Crypto.
4. Run `docker compose --profile aws up -d --build`. No override that publishes 5432 or 0.0.0.0 for 3000/8002.
5. Deploy Nginx config and SSL (certbot for new hostname or IP).
6. Point PROD DNS to new instance; restrict SSH; open only 22 (restricted), 80, 443.

### 8.2 Data migration (Postgres)

- **On Crypto (source):**  
  `docker compose --profile aws exec -T db pg_dump -U trader -d atp --no-owner --no-acl > atp_dump.sql`  
  (or use `pg_dump` from host if client installed.)
- **Copy dump to new instance:** e.g. `scp atp_dump.sql ubuntu@<new-prod-ip>:~/automated-trading-platform/`
- **On new PROD:** Start stack so `db` is up, then:  
  `docker compose --profile aws exec -T db psql -U trader -d atp < atp_dump.sql`
- **Trading config:** Copy `aws_trading_config_data` content if needed (e.g. export from backend or copy volume data); attach to new instance’s backend-aws.

### 8.3 Zero-downtime option

- Bring new PROD up with same app version; migrate DB and config; switch DNS from Crypto to new PROD (reduce TTL beforehand).  
- Or: run both in parallel, migrate DB once, then cut over DNS. No in-place zero-downtime without a load balancer; single-instance cutover is acceptable for typical setups.

---

## 9. Summary Table

| Item | Status / Action |
|------|-----------------|
| **Verdict** | REQUIRES MODERATE CLEANUP BEFORE PROD |
| **Port exposure (repo)** | OK (127.0.0.1 for 3000/8002; no 5432). |
| **Port exposure (server)** | Re-verify; remove any 0.0.0.0 for 5432/8002/3000. |
| **Secrets in repo** | None committed; fix logging/printing in 2 files; optional git history purge. |
| **frontend-aws .env.local** | Remove from env_file for PROD. |
| **Nginx / TLS** | In place; keep as-is. |
| **Reproducibility** | Good; document nginx/SSL and cron for new instances. |
| **Rollback** | Git rollback script + nginx backup + compose down/up. |
| **New PROD instance** | Optional; use §8 if you keep Crypto as LAB only. |

This audit is scoped to the repository and documented deployment; any live checks (e.g. `ss -lntp`, presence of backup files, port 9000) should be re-run on the actual Crypto instance at the time of hardening.
