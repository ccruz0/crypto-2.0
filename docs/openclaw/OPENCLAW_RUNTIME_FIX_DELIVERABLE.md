# OpenClaw Runtime Fix — Root Cause and Patch

## A. Exact Root Cause

| Finding | Evidence |
|---------|----------|
| **OpenClaw runs in a container** | `docker-compose.openclaw.yml` / `docker run` on LAB |
| **Runtime user** | uid=1000 (node), gid=1000 (node) |
| **No docker socket** | `docker exec openclaw ls /var/run/docker.sock` → no-socket |
| **No docker CLI** | `docker exec openclaw which docker` → no-docker-cli |
| **Tools run inside container** | Shell/command tools execute via subprocess in container |
| **Why sudo attempted** | Tools or prompts assume sudo for docker; container has no sudo |

**Root cause:** The OpenClaw container had no Docker socket and no Docker CLI. Tools that run `docker` or `sudo docker` fail because (1) docker binary was missing, (2) socket was not mounted, (3) container user had no docker group access.

---

## B. Exact Files Changed

| File | Change |
|------|--------|
| `docker-compose.openclaw.yml` | Add `/var/run/docker.sock` volume, `group_add: "${DOCKER_GROUP_GID:-988}"` |
| `openclaw/Dockerfile.openclaw` | Add `docker.io` (Debian) / `docker-cli` (Alpine) to apt/apk install |
| `scripts/openclaw/deploy_openclaw_lab_from_mac.sh` | Add `-v /var/run/docker.sock`, `--group-add $DOCKER_GID` to docker run |
| `.env.lab.example` | Add `DOCKER_GROUP_GID` comment |
| `docs/openclaw/OPENCLAW_DOCKER_SOCKET.md` | **New** — doc for socket access |

---

## C. Minimal Patch

Already applied in the files above.

---

## D. Deploy / Restart Steps

**Option 1: docker-compose (recommended)**

On LAB:
```bash
cd /home/ubuntu/automated-trading-platform
git pull origin main
# Ensure DOCKER_GROUP_GID matches host: getent group docker  →  docker:x:988:ubuntu
docker compose -f docker-compose.openclaw.yml build --no-cache openclaw
docker compose -f docker-compose.openclaw.yml up -d openclaw
```

**Option 2: deploy_openclaw_lab_from_mac.sh**

From Mac (repo root):
```bash
OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest ./scripts/openclaw/deploy_openclaw_lab_from_mac.sh
# Or: build + push + deploy (no arg)
./scripts/openclaw/deploy_openclaw_lab_from_mac.sh
```

**Option 3: SSM one-liner**

```bash
aws ssm send-command --instance-ids i-0d82c172235770a0d --region ap-southeast-1 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","git pull origin main","docker compose -f docker-compose.openclaw.yml build --no-cache openclaw","docker compose -f docker-compose.openclaw.yml up -d openclaw"]' \
  --timeout-seconds 600
```

---

## E. Validation (from OpenClaw runtime context)

Run inside the container:

```bash
docker exec openclaw sh -c "whoami && docker ps && docker logs openclaw --tail=3 2>/dev/null || true && test -S /var/run/docker.sock && echo socket-present"
```

**Expected:** `node`, container list, log lines, `socket-present`.
