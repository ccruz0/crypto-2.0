# OpenClaw Docker Group Fix Runbook

**Problem:** OpenClaw logs show `[tools] exec failed: sh: 1: docker: Permission denied` and `sudo: Permission denied`, preventing agents (e.g. Sentinel) from running diagnostics (`docker ps`, `docker logs`, `docker inspect`, `docker restart`).

**Root cause:** The OpenClaw runtime user (`ubuntu`) is not in the `docker` group, so it cannot run Docker commands without sudo. Sudo is intentionally denied for security.

**Solution:** Add the runtime user to the `docker` group. No sudo access, no docker socket mount into the container.

---

## A. Exact System Change Required

| Item | Value |
|------|-------|
| **Runtime user** | `ubuntu` (from `openclaw.service` and `openclaw-update-daemon.service`) |
| **Change** | Add `ubuntu` to the `docker` group |
| **Scope** | LAB instance only (where OpenClaw runs) |
| **Security** | docker group only — no full sudo |

---

## B. Command Sequence

Run on the **LAB instance** (e.g. via SSM: `aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1`):

```bash
# 1. Add ubuntu to docker group
sudo usermod -aG docker ubuntu

# 2. Restart OpenClaw so group membership takes effect
#    (systemd services run with the user's group list at start time)
sudo systemctl restart openclaw

# 3. If using the update daemon, restart it too
sudo systemctl restart openclaw-update-daemon 2>/dev/null || true
```

**Note:** Group membership applies to **new** processes. Existing processes (including the OpenClaw service) keep their old group list until restarted.

---

## C. Verification Output

After applying the fix, run:

```bash
# As ubuntu (or run via: sudo -u ubuntu -i)
docker ps
docker compose -f /home/ubuntu/automated-trading-platform/docker-compose.openclaw.yml ps
```

**Expected:** No "Permission denied". Output shows running containers.

```bash
# Verify run-atp-command (PROD diagnostics) — from OpenClaw or curl
curl -sS -X POST https://dashboard.hilovivo.com/api/agent/run-atp-command \
  -H "Authorization: Bearer $OPENCLAW_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "docker ps"}'
```

**Expected:** `{"ok": true, ...}` with container list in stdout.

---

## D. Service Restart Steps

| Service | Restart command |
|---------|-----------------|
| OpenClaw stack | `sudo systemctl restart openclaw` |
| OpenClaw update daemon | `sudo systemctl restart openclaw-update-daemon` |

---

## E. Startup Validation

The `openclaw.service` includes an `ExecStartPre` that runs `scripts/openclaw/check_docker_access.sh`. If `docker ps` fails (e.g. ubuntu not in docker group), the service fails to start with:

```
OpenClaw tools cannot access Docker. Add runtime user to docker group:
  sudo usermod -aG docker ubuntu
  sudo systemctl restart openclaw
```

---

## Architecture Note

- **LAB:** OpenClaw runs on LAB (EC2 or Mac Mini). The `openclaw.service` and `openclaw-update-daemon.service` run as `User=ubuntu`. Both run `docker compose` and require `ubuntu` in the `docker` group.
- **PROD:** When OpenClaw calls `POST /api/agent/run-atp-command`, the backend uses AWS SSM to run commands on PROD EC2. SSM runs as root; root has Docker access. No change needed on PROD for run-atp-command.
- **Container:** The OpenClaw container does **not** mount the Docker socket (by design). Docker commands for ATP diagnostics are routed via `run-atp-command` to PROD. Host-side components (update daemon, systemd) need docker group on LAB.

---

## Quick Reference

```bash
# Fix (LAB)
sudo usermod -aG docker ubuntu
sudo systemctl restart openclaw

# Verify
sudo -u ubuntu docker ps
```
