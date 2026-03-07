# Cursor prompt: Fix gateway allowedOrigins in the OpenClaw app

**Use this in the OpenClaw repo** (e.g. `~/openclaw` or `ccruz0/openclaw`), not in automated-trading-platform.

Open that repo in Cursor, then paste the prompt below into the chat so the agent can find and fix the real config/gateway startup path.

---

## Context

A wrapper image (built in automated-trading-platform) already:
- Writes `~/.openclaw/openclaw.json` with `gateway.controlUi.allowedOrigins`
- Sets `HOME` so that path is writable
- Passes `OPENCLAW_ALLOWED_ORIGINS` (comma-separated) as env

But the **gateway inside the base image may still ignore that file** and crash with:

```text
non-loopback Control UI requires gateway.controlUi.allowedOrigins
```

So the fix is only half done until the **OpenClaw application code** actually loads this config at runtime.

---

## Prompt to paste in Cursor (with OpenClaw repo open)

```
The wrapper image is not enough.

I need you to verify and, if necessary, implement the real runtime loading of gateway.controlUi.allowedOrigins inside the OpenClaw application code.

Current situation:
- a wrapper container writes ~/.openclaw/openclaw.json
- it sets gateway.controlUi.allowedOrigins
- but the gateway may still ignore that file and crash with:
  "non-loopback Control UI requires gateway.controlUi.allowedOrigins"

Your task:

1. Find the real runtime config loader and gateway startup path in this repo.
   Search in:
   - openclaw.mjs
   - src/gateway/*
   - src/config*
   - any bootstrap or config resolution code

2. Verify whether the gateway already reads:
   - ~/.openclaw/openclaw.json
   - gateway.controlUi.allowedOrigins

3. If it does not, implement it in code.

4. The runtime must support:
   - default allowedOrigins:
     [
       "https://dashboard.hilovivo.com",
       "http://localhost:18789",
       "http://127.0.0.1:18789"
     ]
   - reading ~/.openclaw/openclaw.json
   - overriding with OPENCLAW_ALLOWED_ORIGINS if set

5. Ensure the resolved allowedOrigins is actually passed into the gateway startup config.

6. Add one startup log line:
   gateway.controlUi.allowedOrigins resolved: [N origins]

7. Do not use dangerouslyAllowHostHeaderOriginFallback.
   Do not disable security checks.

8. Return:
   - exact code files changed
   - exact code diff summary
   - exact command to build
   - exact command to verify from logs

Do not stop at docs or wrapper scripts.
I need the real application code path fixed.
```

---

## After the app is fixed

1. Build and push the **OpenClaw app image** (from the OpenClaw repo) to GHCR as usual (e.g. `ghcr.io/ccruz0/openclaw:latest`).
2. Rebuild the **wrapper** in automated-trading-platform from that new base:  
   `docker build -f openclaw/Dockerfile.openclaw -t openclaw-with-origins:latest .`
3. Tag and push the wrapper:  
   `docker tag openclaw-with-origins:latest ghcr.io/ccruz0/openclaw:with-origins`  
   `docker push ghcr.io/ccruz0/openclaw:with-origins`
4. On LAB, pull and run with `OPENCLAW_ALLOWED_ORIGINS` set; check logs for both:
   - `[openclaw-entrypoint] gateway.controlUi.allowedOrigins loaded (N origins)`
   - `gateway.controlUi.allowedOrigins resolved: [N origins]`
   - No "non-loopback Control UI requires gateway.controlUi.allowedOrigins" error.
