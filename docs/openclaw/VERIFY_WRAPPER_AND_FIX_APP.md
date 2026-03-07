# Verify wrapper image and fix app if needed

This runbook: (1) build and push the wrapper image, (2) run it on LAB, (3) check logs to see if the **base app** reads the config. If the gateway still crashes, use the Cursor prompt in this repo to fix the real OpenClaw app code.

---

## 1. Build wrapper (from your Mac, in this repo)

```bash
cd /Users/carloscruz/automated-trading-platform
docker build -f openclaw/Dockerfile.openclaw -t openclaw-with-origins:latest .
```

---

## 2. Push to GHCR (separate tag)

```bash
docker tag openclaw-with-origins:latest ghcr.io/ccruz0/openclaw:with-origins
docker push ghcr.io/ccruz0/openclaw:with-origins
```

(Log in first if needed: `docker login ghcr.io -u ccruz0`.)

---

## 3. On LAB: run the wrapper image

```bash
sudo docker pull ghcr.io/ccruz0/openclaw:with-origins
sudo docker stop openclaw 2>/dev/null || true
sudo docker rm openclaw 2>/dev/null || true
sudo docker run -d --restart unless-stopped \
  -p 8081:18789 \
  -e OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789,http://127.0.0.1:18789 \
  --name openclaw \
  ghcr.io/ccruz0/openclaw:with-origins
sudo docker logs openclaw --tail 100
```

---

## 4. What to look for in logs

**Good sign (wrapper did its job):**

```text
[openclaw-entrypoint] gateway.controlUi.allowedOrigins loaded (3 origins)
```

Then either:

### Success

- No line containing: `non-loopback Control UI requires gateway.controlUi.allowedOrigins`
- Gateway starts and listens (e.g. “listening on ws://…”).
- `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/` returns 200/301/302.

→ The base image already reads the config; you’re done.

### Failure

- You still see: **`Gateway failed to start: Error: non-loopback Control UI requires gateway.controlUi.allowedOrigins`** (or similar).

→ The base app **does not** read `~/.openclaw/openclaw.json` (or env). The wrapper is not enough; the **OpenClaw application code** must be updated.

---

## 5. If the gateway still crashes: fix the app

Open the **OpenClaw repo** (e.g. `~/openclaw`) in Cursor and use the prompt in:

**[CURSOR_PROMPT_FIX_GATEWAY_ALLOWED_ORIGINS.md](CURSOR_PROMPT_FIX_GATEWAY_ALLOWED_ORIGINS.md)**

That prompt tells Cursor to find the real config/gateway startup path and implement loading of `gateway.controlUi.allowedOrigins` from `~/.openclaw/openclaw.json` and `OPENCLAW_ALLOWED_ORIGINS`, then pass it into the gateway so the crash goes away.

After the app is fixed, rebuild and push the **app** image (e.g. `ghcr.io/ccruz0/openclaw:latest`), then rebuild the **wrapper** from that new base and push `ghcr.io/ccruz0/openclaw:with-origins` again; redeploy on LAB and re-check logs.
