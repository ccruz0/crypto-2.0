# OpenClaw frontend: minimal patch and env vars

Apply in the **OpenClaw frontend repo** (builds `ghcr.io/ccruz0/openclaw`). Reference code lives in `docs/openclaw/reference-frontend/` in the ATP repo.

---

## 1) Search results in this workspace (ATP repo)

The **OpenClaw frontend** source (with `WebSocket(`, `ws://localhost:8081`) is **not** in the automated-trading-platform repo. Searches for `localhost:8081`, `WebSocket(`, `ws://`, `wss://`, `SOCKET`, `WS_URL`, `NEXT_PUBLIC`, `VITE_` in **application code** (excluding docs) only find:

- **Dashboard frontend** (`frontend/src/lib/environment.ts`): `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_ENVIRONMENT` (Dashboard API, not OpenClaw WS).
- **Backend** (`backend/app/services/brokers/crypto_com_constants.py`): `WS_USER` / `WS_MARKET` (Crypto.com streams, not OpenClaw).
- **Docs** (multiple `.md` files): mentions of 8081, WebSocket, env vars.

So in the **OpenClaw frontend repo** you must run the same search and replace any matches with the helper below.

---

## 2) Single source of truth for WS URL

**New file:** `src/lib/getOpenClawWsUrl.ts` (or equivalent path in OpenClaw repo)

```ts
const WS_PATH = "/openclaw/ws";

export function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") return "";

  const nextUrl =
    typeof process !== "undefined" && process.env?.NEXT_PUBLIC_OPENCLAW_WS_URL;
  if (nextUrl) return nextUrl;

  const viteUrl =
    typeof import.meta !== "undefined" &&
    (import.meta as unknown as { env?: { VITE_OPENCLAW_WS_URL?: string } })
      .env?.VITE_OPENCLAW_WS_URL;
  if (viteUrl) return viteUrl;

  const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${wsProto}//${window.location.host}${WS_PATH}`;
}
```

**Usage:** Where you have `new WebSocket("ws://localhost:8081")` or similar:

```ts
import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";
const ws = new WebSocket(getOpenClawWsUrl());
```

---

## 3) Base path (/openclaw)

- **Next.js:** In `next.config.js` add:
  - `basePath: process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || ""`
  - `assetPrefix: process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || undefined`
- **Vite:** In `vite.config.*` set:
  - `base: process.env.VITE_OPENCLAW_BASE_PATH || "/"`

Use relative paths for assets/API so they work under `/openclaw/`.

---

## 4) WS route alignment

Default frontend path: **`/openclaw/ws`**. Nginx proxies `location ^~ /openclaw/` to the backend; so a request to `wss://dashboard.hilovivo.com/openclaw/ws` hits the backend. If the backend serves WebSocket at **`/ws`** (not `/openclaw/ws`), either:

- Have the backend mount the WS route at `/openclaw/ws`, or
- Keep Nginx proxying `/openclaw/` to the app root; then backend at `/ws` receives the request as path `/openclaw/ws` unless Nginx strips the prefix. If the backend expects `/ws`, use a dedicated Nginx location for `/openclaw/ws` that proxies to `backend:port/ws`, or change `WS_PATH` in the helper to match what the backend actually serves (and ensure Nginx forwards that path correctly).

---

## 5) Minimal patch (diff-style)

**New file** `src/lib/getOpenClawWsUrl.ts`: contents as in §2.

**Edit** every file that creates the WebSocket (e.g. `refresh.js`, a hook, or a service):

```diff
- const ws = new WebSocket("ws://localhost:8081");
+ import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";
+ const ws = new WebSocket(getOpenClawWsUrl());
```

**Edit** `next.config.js` (Next.js):

```diff
  /** @type {import('next').NextConfig} */
  const nextConfig = {
+   basePath: process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || "",
+   assetPrefix: process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || undefined,
    // ...existing
  };
```

**Edit** `vite.config.ts` (Vite):

```diff
  export default defineConfig({
+   base: process.env.VITE_OPENCLAW_BASE_PATH || "/",
    // ...existing
  });
```

---

## 6) Env vars

| Env var | When | Value |
|--------|------|--------|
| **Prod** (behind Nginx at `https://dashboard.hilovivo.com/openclaw/`) | Build | `NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw` (Next) or `VITE_OPENCLAW_BASE_PATH=/openclaw/` (Vite). |
| **Prod** (optional) | Build | `NEXT_PUBLIC_OPENCLAW_WS_URL` or `VITE_OPENCLAW_WS_URL` — leave unset to use same-origin `/openclaw/ws`. |
| **Local dev** | Dev | `NEXT_PUBLIC_OPENCLAW_WS_URL=ws://localhost:8081/ws` or `VITE_OPENCLAW_WS_URL=ws://localhost:8081/ws` (or your backend WS path). |
| **Local dev** (root) | Dev | Leave base path unset so app is at `/`. |

---

## Acceptance

- At `https://dashboard.hilovivo.com/openclaw/`: console must **not** show `ws://localhost:8081`.
- Network: WebSocket request to `wss://dashboard.hilovivo.com/openclaw/ws` (or configured path) with status **101 Switching Protocols**.
- No placeholder; assets load from `/openclaw/*` without 404s.
