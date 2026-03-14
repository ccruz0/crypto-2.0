# OpenClaw container (ATP reference)

The **OpenClaw image is not built in this repo.** It is built and published from the [ccruz0/openclaw](https://github.com/ccruz0/openclaw) repository.

**Allowed-origins fix (proxy deployment):** This repo provides a **wrapper image** so the gateway starts behind a reverse proxy. Build with `docker build -f openclaw/Dockerfile.openclaw -t openclaw-with-origins:latest .`, set `OPENCLAW_IMAGE=openclaw-with-origins:latest`, and pass `OPENCLAW_ALLOWED_ORIGINS`. See [ALLOWED_ORIGINS_IMPLEMENTATION.md](../docs/openclaw/ALLOWED_ORIGINS_IMPLEMENTATION.md) for exact commands and verification.

## Image

- **Source repo:** `ccruz0/openclaw`
- **Image:** `ghcr.io/ccruz0/openclaw:latest`
- **CI:** GitHub Actions in the openclaw repo build and push on push to `main`. See [APPLY_GHCR_WORKFLOW.md](../docs/openclaw/APPLY_GHCR_WORKFLOW.md) for the workflow to add there.

## Use on LAB

In `.env.lab`:

```bash
OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest
```

Then:

```bash
docker compose -f docker-compose.openclaw.yml up -d
```

The `docker-compose.openclaw.yml` in this repo defaults to `ghcr.io/ccruz0/openclaw:latest` when `OPENCLAW_IMAGE` is not set.

## Redeploy on LAB (after new image in GHCR)

```bash
docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw || true
docker rm openclaw || true
docker run -d --restart unless-stopped -p 8081:8081 --name openclaw ghcr.io/ccruz0/openclaw:latest
```

(Adjust port if your stack uses a different host port.)

## Model routing and gateway compatibility

The wrapper writes `agents.defaults.model.primary` and `fallbacks` into `openclaw.json` (cheap-first by default). For ATP’s fallback chain to work, the **gateway** (in ccruz0/openclaw) must accept the `model` field from each request and return failover-friendly errors. See **[GATEWAY_MODEL_ROUTING_AND_FAILOVER_COMPATIBILITY.md](../docs/GATEWAY_MODEL_ROUTING_AND_FAILOVER_COMPATIBILITY.md)**.

## Docs in this repo

- [GATEWAY_MODEL_ROUTING_AND_FAILOVER_COMPATIBILITY.md](../docs/GATEWAY_MODEL_ROUTING_AND_FAILOVER_COMPATIBILITY.md) — gateway contract for request-body model and failover-friendly errors
- [APPLY_GHCR_WORKFLOW.md](../docs/openclaw/APPLY_GHCR_WORKFLOW.md) — workflow to build/publish from ccruz0/openclaw
- [DEPLOY_REAL_OPENCLAW_APP_ON_LAB.md](../docs/runbooks/DEPLOY_REAL_OPENCLAW_APP_ON_LAB.md) — replace placeholder with real app on LAB
