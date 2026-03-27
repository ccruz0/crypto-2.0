# Docker Setup

How the Automated Trading Platform runs in Docker for local development and production (AWS).

---

## Profiles

| Profile | Use | Services |
|--------|-----|----------|
| **local** | Development on your machine | db, backend-dev (uvicorn --reload), frontend-dev, etc. |
| **aws** | Production on EC2 | db, backend-aws (Gunicorn), frontend-aws, market-updater-aws |

**Production uses only `--profile aws`.** Never run production with `backend-dev` or `uvicorn --reload`.

---

## Main Services (AWS profile)

Defined in root `docker-compose.yml`:

| Service | Role |
|---------|------|
| **db** | PostgreSQL; no public port; backend connects via Docker network. |
| **backend-aws** | FastAPI (Gunicorn + Uvicorn workers). |
| **frontend-aws** | Next.js frontend. |
| **market-updater-aws** | Market data updater. |

Backend and frontend bind to `127.0.0.1` on the host (e.g. 8002, 3000); Nginx on the host reverse-proxies to them.

---

## Environment Files

- **.env** — Base; may be checked in (no secrets) or gitignored.
- **.env.local** — Local overrides (dev).
- **.env.aws** — AWS/production overrides (secrets from vault or EC2 secrets).
- **secrets/runtime.env** — Production secrets on EC2; not in repo.

Compose loads multiple env files; production uses `.env`, `.env.aws`, and optionally `secrets/runtime.env`.

---

## Commands (production, on EC2)

All from project root: `/home/ubuntu/crypto-2.0`.

```bash
# Status
docker compose --profile aws ps

# Logs
docker compose --profile aws logs -n 200 backend-aws
docker compose --profile aws logs -f backend-aws

# Restart
docker compose --profile aws restart backend-aws
docker compose --profile aws restart

# Deploy (pull and up)
docker compose --profile aws pull
docker compose --profile aws up -d --remove-orphans
```

Full reference: [deployment_aws.md](../contracts/deployment_aws.md).

---

## Local development (no production)

```bash
# Start dev stack
docker compose --profile local up -d

# Frontend: http://localhost:3000 (or 3001 per config)
# Backend:  http://localhost:8002
# API docs: http://localhost:8002/docs
```

Do not run `--profile local` backend (SignalMonitorService, scheduler, Telegram) in parallel with AWS production to avoid duplicate alerts and orders.

---

## Never in production

- Do not use `uvicorn --reload` for the backend.
- Do not expose DB or backend ports to the internet; bind to 127.0.0.1 and put Nginx in front.
- Do not mix systemd and Docker Compose for the same service.

---

## Related

- [AWS setup](aws-setup.md)
- [Deploy runbook](../runbooks/deploy.md)
- [Restart services runbook](../runbooks/restart-services.md)
- Root [README.md](../../README.md) — Getting started and deployment policy
