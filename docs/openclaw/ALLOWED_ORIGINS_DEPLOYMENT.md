# OpenClaw allowedOrigins — deployment and Docker usage

When the OpenClaw container runs behind a reverse proxy (e.g. Nginx at `https://dashboard.hilovivo.com/openclaw`), the gateway can fail with:

```text
non-loopback Control UI requires gateway.controlUi.allowedOrigins
```

This document describes the fix (implemented in the **OpenClaw repo**) and how to run the container in ATP (this repo).

---

## Fix overview

1. **In the OpenClaw repo:** The gateway must support `gateway.controlUi.allowedOrigins`:
   - **Defaults:** e.g. `https://dashboard.hilovivo.com`, `http://localhost:18789`, `http://127.0.0.1:18789`.
   - **Config file:** `~/.openclaw/openclaw.json` can set `gateway.controlUi.allowedOrigins`; the app should create this file with sane defaults if it does not exist.
   - **Env override:** `OPENCLAW_ALLOWED_ORIGINS` (comma-separated) overrides the config file.
2. **In ATP:** Use `OPENCLAW_ALLOWED_ORIGINS` when running the container (compose or `docker run`).

Security is preserved: we do **not** disable checks or use `dangerouslyAllowHostHeaderOriginFallback`; we set `allowedOrigins` explicitly.

---

## Docker run (standalone)

After the OpenClaw image is built with the allowedOrigins fix:

```bash
docker run -d \
  -p 8081:18789 \
  -e OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789 \
  --name openclaw \
  ghcr.io/ccruz0/openclaw:latest
```

- `-p 8081:18789` — host port 8081 (e.g. for Nginx upstream) maps to container port 18789 (gateway).
- `-e OPENCLAW_ALLOWED_ORIGINS=...` — allowed origins for the Control UI; include the public origin (dashboard.hilovivo.com) and localhost if you need local access.

With token (read from file in container):

```bash
docker run -d \
  -p 8081:18789 \
  -e OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789 \
  -v /path/on/host/openclaw_token:/run/secrets/openclaw_token:ro \
  --name openclaw \
  ghcr.io/ccruz0/openclaw:latest
```

---

## Docker Compose (ATP)

This repo’s `docker-compose.openclaw.yml` now:

- Sets `OPENCLAW_ALLOWED_ORIGINS` from env (default: `https://dashboard.hilovivo.com,http://localhost:18789,http://127.0.0.1:18789`).
- Maps host port **8081** to container port **18789**.

In `.env.lab` (copy from `.env.lab.example`), you can set:

```bash
OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789,http://127.0.0.1:18789
```

Then:

```bash
docker compose -f docker-compose.openclaw.yml up -d
```

Nginx on the dashboard host should proxy to the host where the container runs, e.g. `http://172.31.3.214:8081` for the LAB instance.

---

## Applying the fix in the OpenClaw repo

Implement the gateway/config changes in the **ccruz0/openclaw** (or your OpenClaw) repo using:

- **Runbook:** [FIX_ALLOWED_ORIGINS_RUNBOOK.md](./FIX_ALLOWED_ORIGINS_RUNBOOK.md)

That runbook includes where to find gateway config, default values, auto-creation of `~/.openclaw/openclaw.json`, env override logic, and an example config loader. After merging and building the image, use the Docker commands above to deploy.
