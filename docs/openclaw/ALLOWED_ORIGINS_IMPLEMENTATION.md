# OpenClaw allowedOrigins — Implementation (in-repo)

This document describes the **code changes in this repository** that implement support for `gateway.controlUi.allowedOrigins` so the gateway starts behind a reverse proxy without disabling security.

---

## 1. Exact files changed

| File | Change |
|------|--------|
| **`openclaw/docker-entrypoint.sh`** | **NEW** — Entrypoint that creates `~/.openclaw/openclaw.json` with default or env-driven `gateway.controlUi.allowedOrigins`, then exec’s the base image CMD. Logs `[openclaw-entrypoint] gateway.controlUi.allowedOrigins loaded (N origins)` for verification. |
| **`openclaw/Dockerfile.openclaw`** | **NEW** — Wrapper image `FROM ghcr.io/ccruz0/openclaw:latest`; sets `OPENCLAW_CONFIG_HOME=/tmp/.openclaw`, copies entrypoint, `ENTRYPOINT ["/openclaw-entrypoint.sh"]`. Base CMD is passed through. |
| **`docker-compose.openclaw.yml`** | **UPDATED** — Comment that wrapper image provides the fix; `OPENCLAW_ALLOWED_ORIGINS` env and port `8081:18789` already present; no volume needed (config under `/tmp`). |

---

## 2. Diff summary

- **openclaw/docker-entrypoint.sh (new):**  
  - Default origins: `https://dashboard.hilovivo.com`, `http://localhost:18789`, `http://127.0.0.1:18789`.  
  - If `OPENCLAW_ALLOWED_ORIGINS` is set, parse comma-separated list and use as `allowedOrigins`.  
  - Write `$OPENCLAW_CONFIG_HOME/openclaw.json` (default `/tmp/.openclaw/openclaw.json`) with `gateway.controlUi.allowedOrigins`.  
  - Set `HOME` so `~/.openclaw` points at that path for the gateway process.  
  - Log one line: `[openclaw-entrypoint] gateway.controlUi.allowedOrigins loaded (N origins)`.  
  - `exec "$@"` to run the base image CMD (e.g. `gateway --bind lan`).

- **openclaw/Dockerfile.openclaw (new):**  
  - `FROM ghcr.io/ccruz0/openclaw:latest`.  
  - `ENV OPENCLAW_CONFIG_HOME=/tmp/.openclaw`.  
  - `COPY openclaw/docker-entrypoint.sh /openclaw-entrypoint.sh`, `RUN chmod +x`.  
  - `ENTRYPOINT ["/openclaw-entrypoint.sh"]`. No `CMD` so base image CMD is used.

- **docker-compose.openclaw.yml:**  
  - Comment added; existing `environment` and `ports` unchanged.

---

## 3. Build command

From the **repository root**:

```bash
docker build -f openclaw/Dockerfile.openclaw -t openclaw-with-origins:latest .
```

Push to GHCR (optional, for LAB):

```bash
docker tag openclaw-with-origins:latest ghcr.io/ccruz0/openclaw:with-origins
docker push ghcr.io/ccruz0/openclaw:with-origins
```

---

## 4. Docker run command (standalone)

```bash
docker run -d \
  -p 8081:18789 \
  -e OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789 \
  --name openclaw \
  openclaw-with-origins:latest
```

With token file:

```bash
docker run -d \
  -p 8081:18789 \
  -e OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789 \
  -v /path/on/host/openclaw_token:/run/secrets/openclaw_token:ro \
  --name openclaw \
  openclaw-with-origins:latest
```

---

## 5. Using with docker-compose

In `.env.lab`:

```bash
OPENCLAW_IMAGE=openclaw-with-origins:latest
OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789,http://127.0.0.1:18789
```

Then from repo root (after building the wrapper image once):

```bash
docker compose -f docker-compose.openclaw.yml up -d
```

---

## 6. Verification command

Confirm from container logs that allowedOrigins was loaded:

```bash
docker logs openclaw 2>&1 | grep "allowedOrigins loaded"
```

**Expected:** One line like:

```text
[openclaw-entrypoint] gateway.controlUi.allowedOrigins loaded (3 origins)
```

Then confirm the gateway is listening:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/
```

Expect `200`, `301`, or `302` (not `000` or connection refused).

---

## 7. Requirement for the fix to take effect

The **base image** (`ghcr.io/ccruz0/openclaw:latest`) must read `gateway.controlUi.allowedOrigins` from either:

1. **`~/.openclaw/openclaw.json`** — The entrypoint sets `HOME` so that `~/.openclaw` is `/tmp/.openclaw` and writes the JSON there before starting the gateway.  
2. **`OPENCLAW_ALLOWED_ORIGINS`** — The entrypoint does not modify env; if the base image reads this env var, set it in compose or `docker run` as above.

If the base image does not yet read from that file or env, the gateway will still fail with “non-loopback Control UI requires gateway.controlUi.allowedOrigins” until the OpenClaw application repo adds that support. The runbook [FIX_ALLOWED_ORIGINS_RUNBOOK.md](FIX_ALLOWED_ORIGINS_RUNBOOK.md) describes the changes to apply in the OpenClaw repo so that this wrapper’s config file and env are used.

---

## 8. Deploy to LAB (EC2 amd64) via S3

LAB is **linux/amd64**. Building the wrapper on a Mac (arm64) produces an **arm64** image; running it on LAB causes `exec format error`. To deploy without GHCR login on LAB:

1. **Build for amd64** (on a Linux amd64 host or CI, e.g. GitHub Actions). Requires the **base image** `ghcr.io/ccruz0/openclaw:latest` to have an **amd64** manifest in GHCR:
   ```bash
   docker build --platform linux/amd64 -f openclaw/Dockerfile.openclaw -t ghcr.io/ccruz0/openclaw:with-origins .
   ```

2. **From your Mac:** save the image, upload to S3, then run on LAB via SSM (replace `YOUR_BUCKET` with your bucket name):
   ```bash
   docker save ghcr.io/ccruz0/openclaw:with-origins | gzip -c > /tmp/openclaw-with-origins.tar.gz
   aws s3 cp /tmp/openclaw-with-origins.tar.gz s3://YOUR_BUCKET/openclaw/openclaw-with-origins.tar.gz --region ap-southeast-1
   aws ssm send-command --instance-ids i-0d82c172235770a0d --region ap-southeast-1 \
     --document-name "AWS-RunShellScript" \
     --parameters '{"commands":["aws s3 cp s3://YOUR_BUCKET/openclaw/openclaw-with-origins.tar.gz /tmp/oc.tar.gz --region ap-southeast-1","gunzip -c /tmp/oc.tar.gz | sudo docker load","sudo docker rm -f openclaw 2>/dev/null; true","sudo docker run -d --name openclaw --restart unless-stopped -p 18789:18789 -e OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789,http://127.0.0.1:18789 ghcr.io/ccruz0/openclaw:with-origins"]}' \
     --timeout-seconds 600 --output text --query 'Command.CommandId'
   ```

3. **Alternative:** Fix GHCR login on LAB (valid PAT with `read:packages` in Parameter Store `/openclaw/ghcr-token`); then LAB can `docker pull` directly. See [ghcr_login_lab.md](../../scripts/openclaw/ghcr_login_lab.md).
