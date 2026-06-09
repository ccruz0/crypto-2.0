# Backend AWS — canonical repo path (PROD)

Short reference for where to run `docker compose --profile aws` on EC2.

## Paths

| Context | Path | Notes |
|---------|------|--------|
| **Canonical PROD repo** | `/home/ubuntu/crypto-2.0` | Use for all new deploys, restarts, and runbook commands |
| **Legacy path** | `/home/ubuntu/automated-trading-platform` | Older clone name; do not use for new deploys unless explicitly in fallback mode |

## Runtime (localhost on EC2)

| Service | Address |
|---------|---------|
| Backend | `http://127.0.0.1:8002` |
| Frontend | `http://127.0.0.1:3000` |
| Public dashboard | `https://dashboard.hilovivo.com` |

## Quick verification (on PROD)

Run from the canonical repo root. No secrets required.

```bash
cd /home/ubuntu/crypto-2.0
git rev-parse --short HEAD
sudo docker compose --profile aws ps
curl -s http://127.0.0.1:8002/ping_fast
curl -s http://127.0.0.1:8002/api/health/ready
```

**Expected:** `git rev-parse` prints a commit SHA; compose shows `backend-aws` and related services up; `ping_fast` and `/api/health/ready` return success when the stack is healthy.

## Related docs

- [deploy.md](../runbooks/deploy.md)
- [restart-services.md](../runbooks/restart-services.md)
- [secrets_runtime_env.md](../runbooks/secrets_runtime_env.md)
