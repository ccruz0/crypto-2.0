# OpenClaw frontend deliverable (copy-paste ready)

This repo (automated-trading-platform) does **not** contain the OpenClaw frontend source that hardcodes `ws://localhost:8081`. The fix must be applied in the **separate OpenClaw frontend repo** that builds `ghcr.io/ccruz0/openclaw`. Run all steps and commands from that repo’s root.

**Búsqueda en AWS (LAB):** En la instancia LAB (`i-0d82c172235770a0d`) el único repo en `/home/ubuntu` es `automated-trading-platform`. El contenedor OpenClaw en ejecución es la imagen **placeholder** `ghcr.io/ccruz0/crypto-2.0:openclaw` (solo `index.html` + `server.py` en `/app`). **El código fuente del frontend OpenClaw no está en LAB.** La imagen real `ghcr.io/ccruz0/openclaw:latest` se construye desde otro repo (p. ej. GitHub `ccruz0/openclaw`); clona ese repo en tu Mac para aplicar este deliverable.

---

## Step A: Find the WebSocket hardcode

From the **OpenClaw frontend repo** root:

```bash
grep -Rn "localhost:8081" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "WebSocket(" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "ws://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "wss://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "WS_URL" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "NEXT_PUBLIC" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "VITE_" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

**Detect framework:**

- Check `package.json`: scripts like `"build": "next build"` → Next.js; `"build": "vite build"` → Vite.
- Presence of `next.config.js` / `next.config.mjs` → Next.js; `vite.config.ts` / `vite.config.js` → Vite.

---

## Step B: Implement WS URL helper

**New file:** `src/lib/getOpenClawWsUrl.ts`

```ts
const WS_PATH = "/openclaw/ws";

export function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") return "";

  const nextUrl = typeof process !== "undefined" && process.env?.NEXT_PUBLIC_OPENCLAW_WS_URL;
  if (nextUrl) return nextUrl;

  const viteUrl = typeof import.meta !== "undefined" && (import.meta as any)?.env?.VITE_OPENCLAW_WS_URL;
  if (viteUrl) return viteUrl;

  const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${wsProto}//${window.location.host}${WS_PATH}`;
}
```

**Replacement:** wherever you have:

```ts
new WebSocket("ws://localhost:8081")
```

use:

```ts
import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";

new WebSocket(getOpenClawWsUrl())
```

(Adjust the import path if your alias differs.)

---

## Step C: Base path support for /openclaw/

**Next.js** — edit `next.config.js` (or `next.config.mjs`):

```js
const basePath = process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || "";

module.exports = {
  basePath,
  assetPrefix: basePath || undefined,
  // ... rest unchanged
};
```

**Vite** — edit `vite.config.ts` (or `vite.config.js`):

```ts
export default defineConfig({
  base: process.env.VITE_OPENCLAW_BASE_PATH || "/",
  // ... rest unchanged
});
```

---

## Step D: Env vars + .env.example

| Env var | Prod (behind Nginx at /openclaw/) | Local dev |
|---------|-----------------------------------|-----------|
| `NEXT_PUBLIC_OPENCLAW_BASE_PATH` | `/openclaw` | unset or `""` |
| `VITE_OPENCLAW_BASE_PATH` | `/openclaw/` | unset or `"/"` |
| `NEXT_PUBLIC_OPENCLAW_WS_URL` | optional (default = same-origin) | e.g. `ws://localhost:8081/ws` if needed |
| `VITE_OPENCLAW_WS_URL` | optional (default = same-origin) | e.g. `ws://localhost:8081/ws` if needed |

**`.env.example` snippet:**

```env
# Prod (served at https://dashboard.hilovivo.com/openclaw/)
NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw
NEXT_PUBLIC_OPENCLAW_WS_URL=

VITE_OPENCLAW_BASE_PATH=/openclaw/
VITE_OPENCLAW_WS_URL=

# Local dev override (only if backend WS is on different port)
# NEXT_PUBLIC_OPENCLAW_WS_URL=ws://localhost:8081/ws
# VITE_OPENCLAW_WS_URL=ws://localhost:8081/ws
```

Default same-origin works when served behind Nginx; override only for local dev if needed.

---

## Step E: Verification

**1) No localhost WS in app code**

```bash
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

**Expected:** No matches (exit code 1 or empty).

**2) Browser acceptance**

- Open **https://dashboard.hilovivo.com/openclaw/**
- Assets load with no 404s (JS/CSS/images under `/openclaw/`).
- DevTools → Network → WS: connection to **wss://dashboard.hilovivo.com/openclaw/ws** with status **101 Switching Protocols**.

---

## Optional: Build / push / deploy

- **Build image:** `docker build -t ghcr.io/ccruz0/openclaw:<tag> .` (use your Dockerfile and tag).
- **Push:** `docker push ghcr.io/ccruz0/openclaw:<tag>`
- **On LAB:** `docker compose -f docker-compose.openclaw.yml pull openclaw && docker compose -f docker-compose.openclaw.yml up -d openclaw`; then `curl -I http://localhost:8080/` → expect 200.
