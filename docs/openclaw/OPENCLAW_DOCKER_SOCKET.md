# OpenClaw Docker Socket Access

**Purpose:** Enable OpenClaw tools to run `docker ps`, `docker logs`, etc. from inside the container without sudo.

## Root cause (fixed)

| Symptom | Cause |
|---------|-------|
| `docker: Permission denied` | Container had no docker socket and no docker CLI |
| `sudo: Permission denied` | Tools attempted sudo; container has no sudo |

## Fix applied

1. **Docker socket mount** in `docker-compose.openclaw.yml`:
   ```yaml
   - /var/run/docker.sock:/var/run/docker.sock
   ```

2. **group_add** so the container process (uid 1000) can access the socket:
   ```yaml
   group_add:
     - "${DOCKER_GROUP_GID:-988}"
   ```
   The host's docker group GID (e.g. 988 on LAB) must match. Get it: `getent group docker`

3. **Docker CLI** in the wrapper image (`openclaw/Dockerfile.openclaw`): `docker.io` (Debian) or `docker-cli` (Alpine)

## DOCKER_GROUP_GID

Set in `.env.lab` if your host's docker group GID differs from 988:

```bash
# On host: getent group docker  →  docker:x:988:ubuntu
DOCKER_GROUP_GID=988
```

## Security note

Mounting the docker socket grants the container full Docker API access (equivalent to root on the host for container operations). This is intentional for tool execution. The container remains non-root, read_only, cap_drop ALL. Do not use on production; LAB only.

## Validation (from OpenClaw runtime context)

Run inside the container:

```bash
docker exec openclaw sh -c "whoami && docker ps && test -S /var/run/docker.sock && echo socket-present"
```

Expected: `node`, container list, `socket-present`.
