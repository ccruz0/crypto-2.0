# Mac Mini OpenClaw Migration Plan

**Date:** 2026-03-15  
**Based on:** [CURRENT_ARCHITECTURE_REPORT.md](CURRENT_ARCHITECTURE_REPORT.md)  
**Goal:** Add Mac Mini home-hosted OpenClaw in parallel with LAB, without changing AWS production trading.

---

## One-Page Executive Recommendation

| Decision | Recommendation |
|----------|----------------|
| **Network** | Tailscale — simplest, no public exposure, works from PROD→Mac Mini and Mac Mini→PROD |
| **Phase 1 scope** | API only: backend calls Mac Mini for `/v1/responses`. UI stays on LAB. |
| **Primary change** | Set `OPENCLAW_API_URL` in `secrets/runtime.env` to Mac Mini Tailscale URL when ready. |
| **Rollback** | Revert `OPENCLAW_API_URL` to `http://172.31.3.214:8080` (LAB). Restart backend. |
| **Cutover criteria** | 10+ successful Notion task executions via Mac Mini; no failures; operator confidence. |
| **LAB retirement** | Only after 30+ days stable Mac Mini; keep LAB as cold standby. |

**Minimal implementation:** Run OpenClaw in Docker on Mac Mini, join Tailscale, expose port 8080. Add Mac Mini Tailscale hostname to PROD `secrets/runtime.env` as `OPENCLAW_API_URL`. No code changes required. Validate with one Notion task.

---

# Part 1: Current OpenClaw Integration Map

## 1.1 Files, Scripts, Docs

| Category | Path | Purpose |
|----------|------|---------|
| **Backend client** | `backend/app/services/openclaw_client.py` | HTTP POST to OpenClaw `/v1/responses`; reads `OPENCLAW_API_URL`, `OPENCLAW_API_TOKEN` |
| **Agent routes** | `backend/app/api/routes_agent.py` | `run-atp-command` — OpenClaw calls PROD; auth via `OPENCLAW_API_TOKEN` |
| **Agent callbacks** | `backend/app/services/agent_callbacks.py` | `_apply_via_openclaw`, `_validate_openclaw_note`, `_verify_openclaw_solution` |
| **Config** | `backend/app/core/config.py` | `OPENCLAW_API_URL`, `OPENCLAW_API_TOKEN`, `OPENCLAW_TIMEOUT_SECONDS` |
| **Compose** | `docker-compose.openclaw.yml` | LAB-only; mounts ATP repo at `/home/node/.openclaw/workspace/atp` |
| **Wrapper** | `openclaw/Dockerfile.openclaw` | Wrapper image for allowed-origins |
| **Deploy script** | `scripts/openclaw/deploy_openclaw_lab_from_mac.sh` | Deploy to LAB via SSM |
| **Nginx block** | `scripts/openclaw/openclaw_nginx_block.txt` | `proxy_pass http://172.31.3.214:8080/` |
| **Fix 504** | `scripts/openclaw/fix_504_via_eice.sh` | Fix OpenClaw 504 via EICE |
| **Workflow** | `.github/workflows/fix_openclaw_504.yml` | Cron 06:00/18:00 UTC |
| **Docs** | `docs/openclaw/*.md` | Runbooks, architecture, prompts |

## 1.2 Environment Variables

| Variable | Where set | Purpose |
|----------|-----------|---------|
| `OPENCLAW_API_URL` | `secrets/runtime.env` (manual) | Backend → OpenClaw base URL. Default in code: `http://172.31.3.214:8080` |
| `OPENCLAW_API_TOKEN` | `secrets/runtime.env` (manual) | Bearer token; must match OpenClaw gateway `auth.token` |
| `OPENCLAW_TIMEOUT_SECONDS` | Optional, default 120 | HTTP timeout |
| `OPENCLAW_*` (model chain, etc.) | `render_runtime_env.sh`, `.env.example` | Model routing, verification; not URL-related |

**Note:** `render_runtime_env.sh` does NOT inject `OPENCLAW_API_URL` or `OPENCLAW_API_TOKEN`. These are added manually to `secrets/runtime.env`.

## 1.3 Runtime Dependencies

| Dependency | Direction | Purpose |
|------------|-----------|---------|
| **PROD backend → OpenClaw** | PROD → OpenClaw | POST `/v1/responses` (prompts, get AI output) |
| **OpenClaw → PROD** | OpenClaw → dashboard.hilovivo.com | POST `/api/agent/run-atp-command` (docker ps, curl, etc.) |
| **Nginx → OpenClaw** | PROD → LAB | Proxy `/openclaw/` for UI (browser → PROD → LAB) |
| **OpenClaw → workspace** | Container | Read ATP repo (mount) |
| **OpenClaw → GitHub** | OpenClaw | Clone, branch, PR (PAT) |
| **OpenClaw → LLM providers** | OpenClaw | OpenAI, Anthropic (API keys in container) |

## 1.4 What Changes if OPENCLAW_API_URL Points to Mac Mini

| Component | Change required |
|-----------|-----------------|
| **openclaw_client.py** | None. Uses `_api_url()` which reads env. |
| **secrets/runtime.env** | Set `OPENCLAW_API_URL=http://<macmini-tailscale>:8080` |
| **Backend restart** | Required after env change |
| **OPENCLAW_API_TOKEN** | Must match Mac Mini OpenClaw gateway token (same token can be shared with LAB for parallel run) |
| **Workspace path** | Mac Mini: mount differs. LAB uses `/home/ubuntu/crypto-2.0`. Mac Mini: e.g. `/Users/<user>/automated-trading-platform` or Docker volume path |
| **run-atp-command** | No change. OpenClaw (Mac Mini) calls `https://dashboard.hilovivo.com/api/agent/run-atp-command` — public URL, outbound from Mac Mini works |
| **Nginx /openclaw/** | No change for Phase 1. UI stays on LAB. PROD nginx continues to proxy to LAB for browser access |

## 1.5 Hardcoded Assumptions in openclaw_client.py

- `_DEFAULT_API_URL = "http://172.31.3.214:8080"` — fallback when env unset
- `_WORKSPACE_NOTE`: "You have read-only access to the project workspace at /home/node/.openclaw/workspace/atp/" — path is in prompt text; Mac Mini mount path will differ inside container but the prompt text can stay (it describes the container path, not host path)
- `_ATP_COMMAND_NOTE`: "POST https://dashboard.hilovivo.com/api/agent/run-atp-command" — correct; Mac Mini reaches this outbound

---

# Part 2: Parallel Mac Mini OpenClaw Plan

## A. Current State

### How OpenClaw works today on LAB

1. **Deployment:** `docker-compose.openclaw.yml` or `deploy_openclaw_lab_from_mac.sh` runs `ghcr.io/ccruz0/openclaw:latest` on atp-lab-ssm-clean (172.31.3.214)
2. **Port:** 8080 (host) → 18789 (container)
3. **Workspace:** `/home/ubuntu/crypto-2.0` mounted at `/home/node/.openclaw/workspace/atp:ro`
4. **Token:** `/home/ubuntu/secrets/openclaw_token` or `gateway.auth.token` in `openclaw.json`
5. **UI:** Nginx on PROD proxies `https://dashboard.hilovivo.com/openclaw/` → `http://172.31.3.214:8080/`
6. **API:** PROD backend sets `OPENCLAW_API_URL=http://172.31.3.214:8080` (or leaves default) and `OPENCLAW_API_TOKEN`; calls POST `/v1/responses`

### What ATP depends on

- **Backend:** `OPENCLAW_API_URL` reachable from PROD (same VPC today)
- **Backend:** `OPENCLAW_API_TOKEN` matches OpenClaw gateway token
- **OpenClaw:** Reachable at URL; responds to POST `/v1/responses` with Bearer auth
- **OpenClaw:** Can call `https://dashboard.hilovivo.com/api/agent/run-atp-command` (outbound)
- **OpenClaw:** Has ATP repo (read-only) for workspace
- **OpenClaw:** Has LLM API keys (OpenAI, Anthropic)

### What can remain unchanged

- Trading, exchange sync, Telegram, dashboard, PostgreSQL — all stay on AWS
- Nginx `/openclaw/` proxy to LAB (UI) — unchanged
- `run-atp-command` endpoint — unchanged
- `openclaw_client.py` — no code change; only env
- LAB OpenClaw — continues to run; fallback when Mac Mini not used

---

## B. Target State

- **AWS PROD:** Only production trading environment. Unchanged.
- **Mac Mini:** Parallel OpenClaw host for API (Notion task investigation, apply, verify). Receives traffic when `OPENCLAW_API_URL` points to it.
- **LAB:** Remains fallback. When `OPENCLAW_API_URL` points to LAB, behavior is today's. When it points to Mac Mini, LAB is idle (or can be stopped to save cost).
- **UI:** Phase 1 — stays on LAB (nginx → LAB). Phase 2 (future) — optional Mac Mini UI via tunnel if desired.

---

## C. Required Changes

### Env vars

| Change | Location | Value |
|--------|----------|-------|
| Add/override | `secrets/runtime.env` on PROD | `OPENCLAW_API_URL=http://<macmini-tailscale-hostname>:8080` |
| Unchanged | `secrets/runtime.env` | `OPENCLAW_API_TOKEN` — same token as LAB (or new token if Mac Mini uses separate gateway config) |

### Scripts

| Script | Change |
|--------|--------|
| `deploy_openclaw_lab_from_mac.sh` | None for Mac Mini. New script: `scripts/openclaw/deploy_openclaw_macmini.sh` (optional) — run Docker on Mac Mini locally |
| `render_runtime_env.sh` | Optional: support `OPENCLAW_API_URL` from SSM parameter for easier switch. Not required for minimal plan. |

### Docker Compose

| File | Change |
|------|--------|
| `docker-compose.openclaw.yml` | None. Mac Mini uses a new file: `docker-compose.openclaw.macmini.yml` (optional) — same image, different volume paths |

### Path/workspace assumptions

| Assumption | LAB | Mac Mini |
|------------|-----|----------|
| Host ATP path | `/home/ubuntu/crypto-2.0` | e.g. `/Users/<user>/automated-trading-platform` |
| Container mount | `-v /home/ubuntu/crypto-2.0:/home/node/.openclaw/workspace/atp:ro` | `-v /Users/<user>/automated-trading-platform:/home/node/.openclaw/workspace/atp:ro` |
| Prompt text | `/home/node/.openclaw/workspace/atp/` | Same — container path is identical |

### Auth/token handling

- **Gateway token:** Mac Mini OpenClaw needs `gateway.auth.token` in its config. Use same token as LAB so `OPENCLAW_API_TOKEN` works for both, or generate new token and update `secrets/runtime.env` when switching.
- **run-atp-command:** OpenClaw sends `Authorization: Bearer <OPENCLAW_API_TOKEN>`. PROD backend validates. Token is in PROD secrets; OpenClaw (Mac Mini) must be configured with the same token in its gateway so it can call run-atp-command. Actually: OpenClaw gateway token is what the backend uses to call OpenClaw. The run-atp-command expects the same token — so the token is shared: backend uses it to call OpenClaw, and OpenClaw uses it to call run-atp-command. So Mac Mini's gateway auth token must equal `OPENCLAW_API_TOKEN` in PROD.

### Docs/runbooks to update

| Doc | Update |
|-----|--------|
| `docs/audit/CURRENT_ARCHITECTURE_REPORT.md` | Add Mac Mini as parallel option |
| `docs/openclaw/README.md` | Add "Mac Mini parallel setup" section |
| `docs/runbooks/secrets_runtime_env.md` | Document `OPENCLAW_API_URL` options (LAB vs Mac Mini) |
| New: `docs/openclaw/MAC_MINI_SETUP.md` | Step-by-step Mac Mini setup |

---

## D. Network Design Options

### Option 1: Tailscale / private network

| Aspect | Detail |
|--------|--------|
| **Setup** | Install Tailscale on PROD EC2 and Mac Mini. Both join same tailnet. |
| **PROD → Mac Mini** | `OPENCLAW_API_URL=http://<macmini-tailscale-name>:8080` or `http://100.x.x.x:8080` |
| **Mac Mini → PROD** | `dashboard.hilovivo.com` is public; Mac Mini reaches it via normal internet |
| **Pros** | No public exposure of Mac Mini; no inbound firewall changes; works from any network |
| **Cons** | PROD must run Tailscale (extra process); Tailscale account required |
| **Security** | Tailscale encrypts; ACLs can restrict which nodes talk to which |

### Option 2: Secure tunnel / reverse proxy (e.g. Cloudflare Tunnel, ngrok)

| Aspect | Detail |
|--------|--------|
| **Setup** | Mac Mini runs cloudflared or ngrok; exposes a public URL (e.g. `https://openclaw-xxx.trycloudflare.com`) |
| **PROD → Mac Mini** | `OPENCLAW_API_URL=https://openclaw-xxx.trycloudflare.com` |
| **Pros** | No Tailscale on PROD; Mac Mini behind NAT works |
| **Cons** | Public URL (even if obscure); tunnel provider in path; URL can change (ngrok free) |
| **Security** | HTTPS; token auth still required; IP allowlist possible if tunnel provider supports |

### Option 3: Public DNS with strict auth and IP restrictions

| Aspect | Detail |
|--------|--------|
| **Setup** | Mac Mini has static IP or dynamic DNS; open port 8080; nginx with IP allowlist for PROD Elastic IP |
| **Pros** | No third-party tunnel |
| **Cons** | Mac Mini must have stable IP; home IP may change; port 8080 exposed to internet (even if restricted) |
| **Security** | Bearer token + IP allowlist; still more exposure than Tailscale |

### Recommendation

**Tailscale** is the safest and simplest for this setup:

1. No public exposure of Mac Mini
2. PROD and Mac Mini can reach each other regardless of home IP changes
3. Single Tailscale install on each host
4. No tunnel provider dependency
5. ACLs can limit PROD to only reach Mac Mini on 8080

**Implementation:** Install Tailscale on PROD (via user-data or manual) and Mac Mini. Use Mac Mini's Tailscale hostname (e.g. `macmini`) or MagicDNS name. Set `OPENCLAW_API_URL=http://macmini:8080` (or `http://100.x.x.x:8080`).

---

## E. Security Boundaries

### Must never be stored on Mac Mini

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (prod)
- `DATABASE_URL` (prod)
- Crypto.com API keys
- `GITHUB_TOKEN` (if used for deploy approvals)
- `ATP_API_KEY` (dashboard auth)
- Any AWS credentials with write access to prod

### Mac Mini access should be read-only for

- ATP repo (workspace mount) — read-only
- No `docker.sock` mount (no ability to control host Docker from OpenClaw)
- No SSH keys to PROD

### Secrets that must remain in AWS only

- All trading and Telegram secrets
- DB credentials
- Exchange keys
- `secrets/runtime.env` on PROD (except `OPENCLAW_API_URL` which can point to Mac Mini)

### Mac Mini may hold

- `OPENCLAW_API_TOKEN` (gateway auth) — same value as in PROD for API calls
- OpenAI/Anthropic API keys (for LLM calls)
- GitHub PAT (for clone/branch/PR) — fine-grained, repo-only
- Tailscale auth

### Firewall and auth model

- **Mac Mini:** Tailscale only for PROD→Mac Mini. No public port 8080.
- **Auth:** Bearer token on `/v1/responses`; OpenClaw gateway validates.
- **run-atp-command:** OpenClaw calls PROD with same token; PROD validates.

---

## F. Rollout Plan

### Step 1: Prepare Mac Mini (no ATP changes)

1. Install Docker on Mac Mini
2. Install Tailscale; join tailnet; note hostname (e.g. `macmini`)
3. Clone ATP repo: `git clone ... automated-trading-platform`
4. Create `docker-compose.openclaw.macmini.yml` (or use existing with path override):
   - Same image: `ghcr.io/ccruz0/openclaw:latest`
   - Mount: `-v $(pwd):/home/node/.openclaw/workspace/atp:ro`
   - Port: `8080:18789`
   - Token: create `openclaw.json` with `gateway.auth.token` = value from LAB (or new token)
5. Run OpenClaw: `docker compose -f docker-compose.openclaw.macmini.yml up -d`
6. **Validation:** From Mac Mini: `curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer <token>" -X POST http://localhost:8080/v1/responses -H "Content-Type: application/json" -d '{"model":"openai/gpt-4o-mini","input":"Hi"}'` → 200

### Step 2: Verify PROD can reach Mac Mini via Tailscale

1. Install Tailscale on PROD EC2 (if not already)
2. From PROD: `curl -s -o /dev/null -w "%{http_code}" http://macmini:8080/` (or Tailscale IP) → 200 or 401
3. **Validation:** PROD can reach Mac Mini on 8080

### Step 3: Add OPENCLAW_API_URL to PROD (parallel, no switch yet)

1. Add to `secrets/runtime.env` on PROD: `OPENCLAW_API_URL_MACMINI=http://macmini:8080` (optional; for testing)
2. Or: create a second backend env file for testing. **Simpler:** do not add yet; go to Step 4.

### Step 4: Switch OPENCLAW_API_URL to Mac Mini (operator decision)

1. On PROD: edit `secrets/runtime.env`: `OPENCLAW_API_URL=http://macmini:8080` (replace LAB URL)
2. Restart backend: `docker compose --profile aws restart backend-aws`
3. **Validation:** Trigger one Notion task (e.g. doc or triage). Check backend logs for `openclaw_client: response received task_id=...` and successful completion.
4. **Validation:** Check Mac Mini OpenClaw logs for incoming request.

### Step 5: Run 10 tasks via Mac Mini

1. Execute 10 Notion tasks (mix of doc, triage, bug)
2. **Validation:** All complete successfully; no timeouts or connection errors
3. **Validation:** run-atp-command works when OpenClaw needs it (check logs)

### Step 6: Document and monitor

1. Update runbooks with Mac Mini setup
2. Add to RUNBOOK_INDEX: "OpenClaw primary: Mac Mini. Fallback: LAB. Switch via OPENCLAW_API_URL."

### Rollback if Mac Mini fails

1. On PROD: edit `secrets/runtime.env`: `OPENCLAW_API_URL=http://172.31.3.214:8080`
2. Restart backend: `docker compose --profile aws restart backend-aws`
3. **Validation:** Next Notion task uses LAB
4. Fix Mac Mini issues; retry when ready

---

## G. Cutover Criteria

### Before switching primary from LAB to Mac Mini

- [ ] 10+ successful Notion task executions via Mac Mini
- [ ] No connection timeouts or 5xx from openclaw_client
- [ ] run-atp-command works when OpenClaw invokes it
- [ ] Operator has run rollback drill (switch back to LAB, verify)
- [ ] Mac Mini uptime acceptable (e.g. always-on, or documented restart procedure)

### Metrics/tests to pass

- `openclaw_client: response received` in backend logs for each task
- No `openclaw_client: connection failed` or `timeout` for Mac Mini URL
- Notion task status progresses to "Investigation Complete" or "Patching" as expected

### When LAB can be retired

- After 30+ days stable Mac Mini as primary
- LAB can be stopped to save cost; keep AMI or runbook to restart if needed
- Do not delete LAB instance permanently; keep as cold standby for 6+ months

---

# Part 3: Change Table

| Change | Why needed | Risk | Owner | Validation | Rollback |
|--------|------------|------|-------|------------|----------|
| Install Tailscale on PROD | PROD must reach Mac Mini | Low; Tailscale is additive | Ops | `curl http://macmini:8080/` from PROD | Uninstall Tailscale |
| Install Tailscale on Mac Mini | Mac Mini reachable from PROD | Low | Ops | Tailscale status shows connected | N/A |
| Run OpenClaw in Docker on Mac Mini | Mac Mini hosts OpenClaw | Low; no prod secrets | Ops | `curl -H "Authorization: Bearer $TOKEN" -X POST http://localhost:8080/v1/responses ...` → 200 | `docker stop openclaw` |
| Set OPENCLAW_API_URL to Mac Mini in secrets/runtime.env | Backend uses Mac Mini for API | Medium; wrong URL = tasks fail | Ops | One Notion task completes | Revert to LAB URL, restart backend |
| Create docker-compose.openclaw.macmini.yml | Mac Mini-specific paths | Low | Ops | Container starts, mount works | Use LAB |
| Update docs (MAC_MINI_SETUP.md, etc.) | Operators know how to use | None | Ops | Doc review | Revert doc changes |
| Add OPENCLAW_API_URL to render_runtime_env from SSM (optional) | Easier switch without SSH | Low | Dev | Render includes URL | Remove from SSM |

---

# Part 4: Minimal Implementation Plan

**Smallest set of changes to get Mac Mini OpenClaw running in parallel.**

## Checklist

1. **Mac Mini**
   - [ ] Install Docker
   - [ ] Install Tailscale; join tailnet; note hostname
   - [ ] Clone ATP repo
   - [ ] Create `openclaw.json` with `gateway.auth.token` (same as LAB or new; if new, update PROD secrets)
   - [ ] Create minimal `openclaw.json` (see docs/openclaw for gateway config; ensure `gateway.auth.token` matches PROD's OPENCLAW_API_TOKEN and `/v1/responses` is enabled)
   - [ ] Run: `docker run -d --restart unless-stopped -p 8080:18789 -v $(pwd):/home/node/.openclaw/workspace/atp:ro -v /path/to/openclaw-home:/home/node/.openclaw -e OPENCLAW_CONFIG_PATH=/home/node/.openclaw/openclaw.json ghcr.io/ccruz0/openclaw:latest`
   - [ ] Verify: `curl -H "Authorization: Bearer $TOKEN" -X POST http://localhost:8080/v1/responses -H "Content-Type: application/json" -d '{"model":"openai/gpt-4o-mini","input":"test"}'` → 200

2. **PROD**
   - [ ] Install Tailscale on EC2 (if not present)
   - [ ] Verify: from PROD, `curl -s -o /dev/null -w "%{http_code}" http://<macmini>:8080/` → 200 or 401

3. **Switch (when ready)**
   - [ ] SSH/SSM to PROD
   - [ ] Edit `secrets/runtime.env`: `OPENCLAW_API_URL=http://<macmini>:8080`
   - [ ] `docker compose --profile aws restart backend-aws`
   - [ ] Trigger one Notion task; verify completion

**No code changes. No new scripts required. No nginx changes.**

**Alternative:** Copy `docker-compose.openclaw.yml` to `docker-compose.openclaw.macmini.yml` and change volume paths to Mac paths (e.g. `$(pwd):/home/node/.openclaw/workspace/atp:ro`, local `openclaw-home` for config). See LAB compose for required env and volume structure.

---

# Part 5: Future Cleanup After Successful Parallel Run

*Only after Mac Mini is proven stable for 30+ days.*

1. **Optional: Mac Mini UI** — If desired, set up tunnel (e.g. cloudflared) so `https://dashboard.hilovivo.com/openclaw-macmini/` proxies to Mac Mini. Or use Tailscale + browser on operator machine.
2. **Optional: Failover logic** — Add `OPENCLAW_API_URL_FALLBACK`; backend tries primary, falls back on timeout. Requires code change in openclaw_client.
3. **Optional: Health check** — Add `/api/health/openclaw` that curls OPENCLAW_API_URL and reports reachable/unreachable.
4. **Optional: SSM parameter** — Store `OPENCLAW_API_URL` in SSM; render_runtime_env reads it. Enables switch without SSH.
5. **LAB cost reduction** — Stop LAB instance when Mac Mini is primary; restart if rollback needed.
6. **Remove fix_openclaw_504 workflow** — If LAB is retired, workflow is obsolete. Update or remove.

---

# Validation and Rollback Checklist

## Validation (after switch to Mac Mini)

- [ ] Backend logs: `openclaw_client: response received task_id=...` for a test task
- [ ] Notion task reaches "Investigation Complete" or "Patching"
- [ ] No `connection failed` or `timeout` in backend logs for openclaw_client
- [ ] Mac Mini container logs show incoming POST to `/v1/responses`
- [ ] run-atp-command works (if task triggers it): OpenClaw calls PROD, gets response

## Rollback (if Mac Mini fails)

- [ ] Edit `secrets/runtime.env` on PROD: `OPENCLAW_API_URL=http://172.31.3.214:8080`
- [ ] `docker compose --profile aws restart backend-aws`
- [ ] Trigger one Notion task; verify it uses LAB (check backend logs for 172.31.3.214)
- [ ] Document incident; fix Mac Mini; retry when ready

---

*End of migration plan*
