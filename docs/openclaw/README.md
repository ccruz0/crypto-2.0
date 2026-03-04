# OpenClaw — Docs index

**Critical:** LAB = atp-lab-ssm-clean (the one running for OpenClaw). OpenAPI is not available in PROD; do not rely on it for audits. **Source of truth:** [INSTANCE_SOURCE_OF_TRUTH.md](../runbooks/INSTANCE_SOURCE_OF_TRUTH.md). **Audit prompts (Cursor + OpenClaw):** [CURSOR_AND_OPENCLAW_AUDIT_PROMPTS.md](../audit/CURSOR_AND_OPENCLAW_AUDIT_PROMPTS.md).

## Open OpenClaw and run audit (do this now)

**[OPEN_OPENCLAW_AND_AUDIT_NOW.md](OPEN_OPENCLAW_AND_AUDIT_NOW.md)** — Steps 1–5: confirm PROD vs LAB, start OpenClaw on LAB, point PROD nginx at LAB private IP, security group, and the audit prompt to paste into OpenClaw.

## Get OpenClaw working on the dashboard

**Validate in one command (from your machine, no SSH):**
```bash
./scripts/openclaw/run_openclaw_diagnosis_local.sh
```
- **401** on `/openclaw/` and `/openclaw/ws` = proxy and upstream OK; open **https://dashboard.hilovivo.com/openclaw/** in the browser and use Basic auth.
- **404** / **504** = script prints the exact **NEXT ACTION**. Full path: [OPENCLAW_AT_DASHBOARD_QUICK.md](OPENCLAW_AT_DASHBOARD_QUICK.md).

**Step-by-step checklist (OpenClaw host → Dashboard host → browser):** [GET_OPENCLAW_WORKING_ON_DASHBOARD.md](GET_OPENCLAW_WORKING_ON_DASHBOARD.md).

Use it when you want the OpenClaw UI at **https://dashboard.hilovivo.com/openclaw** (iframe + Basic Auth). If you hit 404 or 504, that doc links to the right runbooks.

### Fix WebSocket (do this in the OpenClaw frontend repo, not ATP)

**If you’re in ATP and see “Wrong repo open”:** [OPEN_OPENCLAW_REPO_THEN_RUN_PLAN.md](OPEN_OPENCLAW_REPO_THEN_RUN_PLAN.md) — **File → Open Folder** → select the OpenClaw frontend repo, then run the full plan (Steps 1–7) there.

**[OPENCLAW_WS_FIX_RUNBOOK.md](OPENCLAW_WS_FIX_RUNBOOK.md)** — Run in the repo that builds `ghcr.io/ccruz0/openclaw`. Steps: run greps (paste outputs back for exact diff), add `getOpenClawWsUrl.ts`, replace hardcoded `ws://localhost...`, .env.example, verify, build/deploy. [DO_THIS_IN_OPENCLAW_REPO.md](DO_THIS_IN_OPENCLAW_REPO.md) is an alternate short version.  
**→ Cursor prompt (paste in OpenClaw repo):** [CURSOR_PROMPT_WS_FIX_OPENCLAW_REPO.md](CURSOR_PROMPT_WS_FIX_OPENCLAW_REPO.md) — copy a prompt block (3 variants: full, short, non-negotiables+deliverable) and paste into Cursor with the OpenClaw frontend repo open.

**Build real image (replace placeholder):** [CURSOR_PROMPT_OPENCLAW_REAL_BUILD.md](CURSOR_PROMPT_OPENCLAW_REAL_BUILD.md) — Prompt para Cursor en **ccruz0/openclaw**.
**Prompt WS + base path (pegar en openclaw):** [CURSOR_PROMPT_OPENCLAW_WS_AND_BASEPATH_PASTE.md](CURSOR_PROMPT_OPENCLAW_WS_AND_BASEPATH_PASTE.md) — Mismo objetivo, pasos 1–9: detect framework, buscar WS, helper, reemplazar, base path, .env.example, Docker, checklist.
**Runbook paso a paso (aplicar en ccruz0/openclaw):** [OPENCLAW_REPO_FIX_RUNBOOK.md](OPENCLAW_REPO_FIX_RUNBOOK.md) — Detección de framework, helper WS, base path, build/push, verificación y deploy en LAB.

---

## Architecture

| Doc | Purpose |
|-----|--------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | High-level: Lab vs Production separation, capabilities, egress. |
| [ARCHITECTURE_V1_1_INTERNAL_SERVICE.md](ARCHITECTURE_V1_1_INTERNAL_SERVICE.md) | **Dashboard ↔ OpenClaw**: internal service model, Nginx contract, security, guardrails. |
| [ARCHITECTURE_V1_1_ACCEPTANCE_CHECKLIST.md](ARCHITECTURE_V1_1_ACCEPTANCE_CHECKLIST.md) | 10 checks for “production locked” (no OpenClaw on public internet). |

## Operational runbooks (v1.1)

| Runbook | When to use |
|---------|-------------|
| [OPENCLAW_PRIVATE_NETWORK_MIGRATION.md](OPENCLAW_PRIVATE_NETWORK_MIGRATION.md) | Migrate OpenClaw to private-only; Nginx proxy on Dashboard. |
| [OPENCLAW_AT_DASHBOARD_QUICK.md](OPENCLAW_AT_DASHBOARD_QUICK.md) | **Quick path:** 3 things in order (LAB → Nginx PROD → browser). Validation in 2 min (PROD + LAB commands). 401 = healthy. |
| [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md) | 504 en `/openclaw/`: validación por invariantes (3 comandos → 1 cambio; sin interpretar, solo pegar). |
| [FIX_OPENCLAW_308_REDIRECT.md](FIX_OPENCLAW_308_REDIRECT.md) | 308/404 routing issues for `/openclaw`. |
| [OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md](OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md) | Blank iframe after auth (headers/401). |
| [OPENCLAW_PLACEHOLDER_AND_WEBSOCKET.md](OPENCLAW_PLACEHOLDER_AND_WEBSOCKET.md) | Page shows "Placeholder" or console error `WebSocket connection to 'ws://localhost:8081/' failed` — deploy real image on LAB; app must use same-origin WebSocket URL. |
| [OPENCLAW_FRONTEND_WEBSOCKET_AND_BASEPATH.md](OPENCLAW_FRONTEND_WEBSOCKET_AND_BASEPATH.md) | **Implementation guide for the OpenClaw frontend repo:** remove `ws://localhost:8081`, use env `NEXT_PUBLIC_OPENCLAW_WS_URL` / `VITE_OPENCLAW_WS_URL` + same-origin `/openclaw/ws`, basePath for `/openclaw/`. |
| [OPENCLAW_END_TO_END_EXECUTION.md](OPENCLAW_END_TO_END_EXECUTION.md) | **Tight execution path:** (1) deploy real image on LAB, (2) fix WebSocket in OpenClaw frontend repo and rebuild, (3) confirm Nginx WS headers, (4) browser test. Includes search commands to find WS usage in the frontend repo. |
| [OPENCLAW_FRONTEND_PATCH_AND_ENV.md](OPENCLAW_FRONTEND_PATCH_AND_ENV.md) | **Minimal patch + env vars** for OpenClaw frontend: WS helper, basePath, diff-style edits, backend WS path note. Reference code in `reference-frontend/`. |
| [CURSOR_PROMPT_OPENCLAW_FRONTEND_WS_AND_BASEPATH.md](CURSOR_PROMPT_OPENCLAW_FRONTEND_WS_AND_BASEPATH.md) | **Cursor prompt to run in the OpenClaw frontend repo:** find/fix ws://localhost:8081, add same-origin WS helper, support /openclaw base path. Copy prompt into Cursor with that repo open. |
| [OPENCLAW_FRONTEND_DELIVERABLE.md](OPENCLAW_FRONTEND_DELIVERABLE.md) | **Copy-paste deliverable** for the OpenClaw frontend repo (not in this workspace): commands to find WS hardcode, WS URL helper, basePath (Next/Vite), env table, .env.example, verification, acceptance checks, optional build/push/deploy. Includes **AWS search result**: frontend source is not on LAB; only ATP repo + placeholder image there; real app image built from separate repo (e.g. `ccruz0/openclaw`). |
| [APPLY_IN_OPENCLAW_REPO.md](APPLY_IN_OPENCLAW_REPO.md) | **Step-by-step (1–7)** to apply in the OpenClaw frontend repo: identify framework, find WS usage, add `getOpenClawWsUrl`, replace hardcoded URL, base path (if needed), .env.example, verification commands. |
| [OPENCLAW_FRONTEND_WS_FIX_DELIVERABLE.md](OPENCLAW_FRONTEND_WS_FIX_DELIVERABLE.md) | **Full deliverable** for the OpenClaw frontend repo: Steps A–G (framework, locate WS, helper, replace URLs, base path if needed, .env.example), minimal diffs, verification commands and expected outputs. Run `scripts/openclaw/openclaw_frontend_ws_apply.sh` from that repo for detection + verification. |

### On-server: check and start OpenClaw (CLO/OpenCLO instance)

**Option A — Via SSM (from your machine, when Dashboard instance is Online):**

```bash
./scripts/openclaw/run_openclaw_check_via_ssm.sh
```

This runs `check_and_start_openclaw.sh` on the Dashboard instance via AWS SSM and prints the same diagnostics. If you see *SSM PingStatus: ConnectionLost*, use Option B.

**Option B — On the server (SSH or EC2 Instance Connect):**

```bash
cd /home/ubuntu/automated-trading-platform
sudo bash scripts/openclaw/check_and_start_openclaw.sh
```

Then paste the two blocks it prints (`systemctl status openclaw` and `curl -I` for `/openclaw/`) to diagnose service vs nginx vs port.

### Scripts (fast paths)

- **`./scripts/openclaw/run_openclaw_diagnosis_local.sh`** — From your machine: curl `/openclaw/` and `/openclaw/ws`, optional SSM check. No SSH. Classifies 404/504/401 and prints NEXT ACTION. Use this first.
- **`./scripts/openclaw/run_504_diagnosis_ssm.sh`** — Use when you see **504 / upstream timeout**.
  - Runs the 3-step 504 triage via **SSM**.
  - If SSM is **ConnectionLost**, it exits early by design.

- **`./scripts/openclaw/print_504_manual_commands.sh`**
  - Prints the same 3 commands in the correct order for **manual copy/paste**.
  - Use this path when SSM is **ConnectionLost**:
    - Connect via **EC2 Instance Connect** to the Dashboard host.
    - Run block 1 → copy `proxy_pass` IP.
    - Run block 2 with `UPSTREAM_IP` replaced.
    - Run block 3 on the OpenClaw host.
    - Paste the 3 outputs into the incident thread to get the single next change.

- **`./scripts/openclaw/fix_openclaw_proxy_prod.sh`** — On PROD: point `/openclaw/` at LAB private IP (172.31.3.214). Idempotent: backups only in `/etc/nginx/backups/`, moves any `*.bak*`/`*.backup*` out of `sites-enabled`, then backup → replace → `nginx -t` (restore on failure) → reload. See [NGINX_OPENCLAW_PROXY_TO_LAB_PRIVATE_IP.md](../runbooks/NGINX_OPENCLAW_PROXY_TO_LAB_PRIVATE_IP.md).
- **`./scripts/openclaw/insert_nginx_openclaw_block.sh [OPENCLAW_PRIVATE_IP]`**
  - Run **on the Dashboard host** (via EC2 Instance Connect or SSH) to insert the OpenClaw proxy block into the Nginx 443 config. Fixes **404** for `/openclaw` when the block is missing.
  - Example: `sudo ./scripts/openclaw/insert_nginx_openclaw_block.sh 172.31.3.214` (IP privada del LAB/OpenClaw). Requires repo on the server: `git pull` then run the script.

## Other

- [OPENCLAW_DIAGNOSTIC_REPORT.md](OPENCLAW_DIAGNOSTIC_REPORT.md) — Template + manual commands when SSM is unavailable; paste outputs to classify and get NEXT ACTION.
- [OPENCLAW_UI_IN_DASHBOARD.md](OPENCLAW_UI_IN_DASHBOARD.md) — UI embedding in Dashboard.
- [DEPLOY_OPENCLAW_NGINX_PROD.md](DEPLOY_OPENCLAW_NGINX_PROD.md) — Nginx prod deployment.
- [SECURITY.md](SECURITY.md), [COST_MODEL.md](COST_MODEL.md), [MANDATES_AND_RULES.md](MANDATES_AND_RULES.md).
