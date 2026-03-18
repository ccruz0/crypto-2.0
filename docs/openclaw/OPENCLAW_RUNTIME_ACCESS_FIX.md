# OpenClaw Runtime Access Fix

**Date:** 2026-03-16  
**Scope:** Docker access, log visibility, runtime diagnostics for evidence-based ATP investigations

---

## A. Root Cause

| Issue | Root cause | File/config responsible |
|-------|------------|--------------------------|
| **Docker access fails** | OpenClaw runs inside a container (user 1000:1000) with no Docker socket. Tools that run `docker` locally fail. | `docker-compose.openclaw.yml` (no socket mount by design) |
| **Log file missing** | Agent expects `/var/log/openclaw.log` but the real path is `/var/log/openclaw/` (directory) or `docker logs openclaw`. | Volume mount `openclaw_logs:/var/log/openclaw` |
| **PROD vs LAB split** | `run-atp-command` targets PROD only. OpenClaw (on LAB) had no way to get its own logs or inspect LAB containers. | `atp_ssm_runner.py` (PROD instance only) |

---

## B. Minimal Patch Set

| File | Change | Why |
|------|--------|-----|
| `backend/app/services/lab_ssm_runner.py` | **New** | Run allowed commands on LAB via SSM (docker logs openclaw, docker ps, whoami, etc.) |
| `backend/app/services/atp_ssm_runner.py` | Add `docker logs`, `docker inspect` to allowlist | Enable container log/inspect for PROD |
| `backend/app/api/routes_agent.py` | Add `run-lab-command`, `lab-instance-info`, `runtime-diagnostics` | Expose LAB commands and diagnostic endpoint |
| `backend/app/services/openclaw_client.py` | Update `_ATP_COMMAND_NOTE` with run-lab-command, log path | Prompt agents to use APIs, not local docker |
| `docs/openclaw/OPENCLAW_RUNTIME_LOGS.md` | **New** | Document log sources and common mistakes |
| `scripts/openclaw/verify_runtime_visibility.sh` | **New** | Manual diagnostic: whoami, docker ps, log path |

---

## C. Commands to Apply

**On LAB** (if not already done):

```bash
sudo usermod -aG docker ubuntu
# Restart if using systemd:
sudo systemctl restart openclaw 2>/dev/null || true
```

**No restart required** for backend changes — deploy as usual (e.g. `docker compose --profile aws restart backend-aws` on PROD).

**IAM:** The backend's AWS credentials must allow `ssm:SendCommand` to both PROD (i-087953603011543c5) and LAB (i-0d82c172235770a0d). Add LAB instance to the policy if run-lab-command returns "Access Denied".

---

## D. Validation

After deploy, verify:

1. **OpenClaw runtime user**: `ubuntu` on LAB host; `node` (1000:1000) inside container.
2. **docker ps (PROD)**: `curl -X POST https://dashboard.hilovivo.com/api/agent/run-atp-command -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"command": "docker ps"}'` → `ok: true`.
3. **docker logs (LAB)**: `curl -X POST https://dashboard.hilovivo.com/api/agent/run-lab-command -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"command": "docker logs openclaw --tail=50"}'` → `ok: true` with log output.
4. **Runtime diagnostics**: `curl -H "Authorization: Bearer $TOKEN" https://dashboard.hilovivo.com/api/agent/runtime-diagnostics` → `lab.whoami_ok`, `lab.docker_ps_ok`, `atp_prod.docker_ps_ok`.
5. **Manual check on LAB**: `bash scripts/openclaw/verify_runtime_visibility.sh` → all OK.

---

## E. Rollback

| Change | Rollback |
|--------|----------|
| `lab_ssm_runner.py` | Delete file; remove `run-lab-command`, `lab-instance-info`, `runtime-diagnostics` from `routes_agent.py` |
| `atp_ssm_runner.py` | Revert added `docker logs`, `docker inspect` patterns |
| `openclaw_client.py` | Revert `_ATP_COMMAND_NOTE` to previous text |
| `verify_runtime_visibility.sh` | Delete file (optional; no runtime impact) |

No database or config changes. Redeploy backend to roll back.
