# OpenClaw repo fix runbook (apply in ccruz0/openclaw)

**Use this when the repo open in Cursor is ccruz0/openclaw (NOT automated-trading-platform).**

Goal: frontend works behind https://dashboard.hilovivo.com/openclaw/ — no hardcoded `ws://localhost:8081`, same-origin WebSocket, base path `/openclaw`, build and push `ghcr.io/ccruz0/openclaw:latest`.

---

## Step 1 — Detect framework

Run in repo root:

```bash
cat package.json | head -50
ls -la
ls src 2>/dev/null || ls app 2>/dev/null || true
```

- **Next.js:** `next` in dependencies, `next.config.js` or `next.config.mjs`, often `app/` or `pages/`.
- **Vite:** `vite` in devDependencies, `vite.config.ts` or `vite.config.js`, often `src/`.
- **Other:** note the build tool and entry (e.g. `index.html` at root for Vite).

---

## Step 2 — Find WebSocket usage

```bash
grep -Rn "ws://localhost" . --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" 2>/dev/null || true
grep -Rn "localhost:8081" . --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" 2>/dev/null || true
grep -Rn "new WebSocket(" . --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" 2>/dev/null || true
grep -Rn '"/ws"' . --include="*.ts" --include="*.tsx" 2>/dev/null || true
```

Note every file and line where the WS URL is built or used.

---

## Step 3 — Add WebSocket URL helper

Create one helper used everywhere.

**Path (adjust if your app has no `src/lib`):** `src/lib/getOpenClawWsUrl.ts` or `src/utils/getOpenClawWsUrl.ts`.

**Content:**

```ts
/**
 * OpenClaw WebSocket URL. Same-origin when served under /openclaw (e.g. dashboard.hilovivo.com/openclaw/).
 * Env override for local dev: NEXT_PUBLIC_OPENCLAW_WS_URL or VITE_OPENCLAW_WS_URL.
 */
export function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") {
    return ""; // SSR: no WS in server
  }
  const envUrl =
    (import.meta as unknown as { env?: Record<string, string> })?.env?.VITE_OPENCLAW_WS_URL ??
    (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_OPENCLAW_WS_URL);
  if (envUrl) {
    const base = window.location.origin;
    if (envUrl.startsWith("ws")) return envUrl;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}${envUrl.startsWith("/") ? envUrl : `/${envUrl}`}`;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/openclaw/ws`;
}
```

- **Vite only:** you can use only `import.meta.env.VITE_OPENCLAW_WS_URL` and drop the `process.env.NEXT_PUBLIC_OPENCLAW_WS_URL` branch.
- **Next.js only:** use only `process.env.NEXT_PUBLIC_OPENCLAW_WS_URL` and drop the Vite branch.

Simpler browser-only version (no SSR):

```ts
export function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") return "";
  const env = (import.meta as any)?.env?.VITE_OPENCLAW_WS_URL ?? (process as any)?.env?.NEXT_PUBLIC_OPENCLAW_WS_URL;
  if (env && typeof env === "string") {
    if (env.startsWith("ws")) return env;
    const p = window.location.protocol === "https:" ? "wss:" : "ws:";
    return p + "//" + window.location.host + (env.startsWith("/") ? env : "/" + env);
  }
  const p = window.location.protocol === "https:" ? "wss:" : "ws:";
  return p + "//" + window.location.host + "/openclaw/ws";
}
```

---

## Step 4 — Replace hardcoded WebSocket URL

In every file found in Step 2:

- Remove any literal `ws://localhost:8081` or `"ws://localhost:8081"` or similar.
- Import the helper: `import { getOpenClawWsUrl } from '@/lib/getOpenClawWsUrl';` (adjust path).
- Use it where you open the socket, e.g.:

  ```ts
  const ws = new WebSocket(getOpenClawWsUrl());
  ```

Ensure no other file constructs a WS URL manually; all should use `getOpenClawWsUrl()`.

---

## Step 5 — Base path `/openclaw`

**Next.js** (e.g. `next.config.js` or `next.config.mjs`):

```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  basePath: "/openclaw",
  assetPrefix: "/openclaw/",
  // ... rest
};
export default nextConfig;
```

**Vite** (e.g. `vite.config.ts`):

```ts
export default defineConfig({
  base: "/openclaw/",
  // ... rest
});
```

After changing base path, run the dev server and open `http://localhost:PORT/openclaw/` to confirm assets and routes work under `/openclaw/`.

---

## Step 6 — Env example

In `.env.example` (or doc for env vars):

```bash
# Optional: override WebSocket URL (e.g. local dev). If unset, same-origin /openclaw/ws is used.
# VITE_OPENCLAW_WS_URL=ws://localhost:8081
# NEXT_PUBLIC_OPENCLAW_WS_URL=ws://localhost:8081
# Production (served under /openclaw): leave unset to use wss://dashboard.hilovivo.com/openclaw/ws
OPENCLAW_WS_URL=/openclaw/ws
```

Use the name that matches your framework (`VITE_*` or `NEXT_PUBLIC_*`).

---

## Step 7 — Build and publish image

Ensure the Dockerfile builds the frontend with the correct base path (so the image serves the app under `/openclaw/` if needed, or the app is built with `base`/`basePath` so the server can serve it under a subpath).

**Typical flow:**

```bash
# From ccruz0/openclaw repo root
docker build -t ghcr.io/ccruz0/openclaw:latest .
docker push ghcr.io/ccruz0/openclaw:latest
```

If the image is built via CI (e.g. GitHub Actions), trigger that workflow after merging the changes; the runbook in ATP describes deploying that image on LAB.

---

## Step 8 — Deploy on LAB (from ATP docs)

On the LAB server (after image is pushed):

```bash
docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw
docker rm openclaw
docker run -d -p 8081:8081 --name openclaw ghcr.io/ccruz0/openclaw:latest
```

(Or use your existing compose/systemd flow with the new image.)

---

## Step 9 — Verification

1. **Browser:** Open https://dashboard.hilovivo.com/openclaw/
   - No “Placeholder. Replace OPENCLAW_IMAGE...” — real OpenClaw UI.
2. **DevTools Console:** No error “WebSocket connection to ws://localhost:8081 failed”.
3. **DevTools Network → WS:** One connection to `wss://dashboard.hilovivo.com/openclaw/ws` with status 101 (Switching Protocols).
4. **Smoke test:** Send one message in the chat and confirm it is sent/received (or that the UI responds).

---

## Deliverables checklist

- [ ] List of changed files (e.g. `src/lib/getOpenClawWsUrl.ts`, `src/.../Chat.tsx`, `next.config.js` or `vite.config.ts`, `.env.example`).
- [ ] Diffs for each change (helper, WS call sites, config).
- [ ] Exact `docker build` and `docker push` commands (or CI workflow name).
- [ ] Env vars: `VITE_OPENCLAW_WS_URL` or `NEXT_PUBLIC_OPENCLAW_WS_URL` (optional override); production uses same-origin `/openclaw/ws` when unset.
- [ ] Short note: “Deploy on LAB: docker pull + restart” (or link to ATP runbook).

Use this runbook inside **ccruz0/openclaw**; do not change **automated-trading-platform** for this fix.
