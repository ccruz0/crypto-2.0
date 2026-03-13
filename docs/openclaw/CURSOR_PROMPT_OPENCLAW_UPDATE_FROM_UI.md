# Cursor prompt: Make "Update now" work in Docker (OpenClaw repo)

**Paste this into Cursor with the ccruz0/openclaw repo open.**

---

## Goal

The "Update now" button currently runs `npm i -g openclaw@latest`, which fails in Docker (read-only filesystem, non-root). When OpenClaw runs in Docker, the button should instead call a host-side update daemon that runs `docker compose pull && docker compose up -d`.

## Context

- ATP provides a daemon on the host at `http://host.docker.internal:19999/update`
- The container gets `OPENCLAW_UPDATE_DAEMON_URL` from env (set by docker-compose)
- The daemon requires `Authorization: Bearer <gateway_token>`
- The gateway token is in the config (e.g. `gateway.auth.token` in openclaw.json)

## Task

1. **Find** where the "Update now" button triggers the update (search for `npm i -g openclaw`, `npm install`, version check, or update logic).

2. **Branch** the update flow:
   - If `OPENCLAW_UPDATE_DAEMON_URL` is set (or `process.env.OPENCLAW_UPDATE_DAEMON_URL`), use the daemon flow.
   - Otherwise, keep the existing npm install flow for local installs.

3. **Daemon flow:**
   - Get the gateway token (from config, env, or wherever the app already reads it for API auth).
   - `POST` to `OPENCLAW_UPDATE_DAEMON_URL` with:
     - `Authorization: Bearer <token>`
     - `Content-Type: application/json`
     - Body: `{}` or empty
   - On 200: show success, optionally `setTimeout(() => window.location.reload(), 10000)`.
   - On 4xx/5xx: show error from response body or status.

4. **Example (TypeScript/JavaScript):**

```ts
async function performUpdate(): Promise<void> {
  const daemonUrl = process.env.OPENCLAW_UPDATE_DAEMON_URL || (typeof window !== "undefined" && (window as any).__OPENCLAW_UPDATE_DAEMON_URL__);
  const token = getGatewayToken(); // however you get it for API calls

  if (daemonUrl && token) {
    const res = await fetch(daemonUrl, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    });
    if (res.ok) {
      showSuccess?.("Update started. The page will reload when ready.");
      setTimeout(() => window.location.reload(), 10_000);
    } else {
      const err = await res.json().catch(() => ({}));
      showError?.(`Update failed: ${(err as any).error || res.status}`);
    }
  } else {
    await runNpmInstall(); // existing flow
  }
}
```

5. **Env:** If the app is built at image build time, ensure `OPENCLAW_UPDATE_DAEMON_URL` is passed at runtime (e.g. via `NEXT_PUBLIC_` or `VITE_` prefix if needed for client-side, or read from a runtime config endpoint).

## Verification

- Build and push the image.
- Deploy on LAB (or use `./scripts/openclaw/deploy_openclaw_lab_from_mac.sh deploy` from ATP).
- Open the Control UI, click "Update now". It should succeed and the page should reload after ~10s.

## Reference

ATP doc: `docs/openclaw/OPENCLAW_UPDATE_FROM_UI.md` (in the automated-trading-platform / crypto-2.0 repo).
