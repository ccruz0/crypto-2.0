# OpenClaw Runtime Logs

**For agents and investigations:** How to access OpenClaw runtime logs.

## Log sources

| Source | Path / Command | How to access |
|--------|----------------|---------------|
| **Docker stdout/stderr** | `docker logs openclaw --tail=N` | Via `POST /api/agent/run-lab-command` with `{"command": "docker logs openclaw --tail=200"}` |
| **App file logs** | `/var/log/openclaw/` (directory) | Inside container: `ls /var/log/openclaw`, `cat /var/log/openclaw/*.log` |
| **Common mistake** | `/var/log/openclaw.log` | **Does not exist.** Use the directory or `docker logs` via run-lab-command. |

## Why `/var/log/openclaw.log` does not exist

- The container mounts a volume at `/var/log/openclaw` (directory).
- The OpenClaw app may write to files under `/var/log/openclaw/` or to stdout (captured by `docker logs`).
- There is no single file `/var/log/openclaw.log` unless the app creates it.

## For evidence-based investigations

1. **ATP PROD** (containers, scheduler, backend): Use `POST /api/agent/run-atp-command` with commands like `docker compose --profile aws ps`, `docker compose --profile aws logs --tail=100 backend-aws`.
2. **OpenClaw LAB** (own logs, LAB containers): Use `POST /api/agent/run-lab-command` with `docker logs openclaw --tail=200`.
3. **Runtime diagnostics**: `GET /api/agent/runtime-diagnostics` (with Bearer token) returns whoami, docker ps status, and log path note.
