# OpenClaw frontend: WebSocket URL and basePath for reverse proxy

Apply these changes **in the OpenClaw frontend repo** (the one that builds the UI and currently uses `ws://localhost:8081`). Goal: work when served at `https://dashboard.hilovivo.com/openclaw/` and in local dev.

---

## 1. Find where the WebSocket URL is defined

Search in the OpenClaw frontend repo for:

- `localhost:8081`
- `ws://` or `wss://`
- `WebSocket(`
- `socket` (variable or module name)
- `WS_URL`, `VITE_`, `NEXT_PUBLIC_`

Typical locations: a config file, an env helper, or the file that creates the WebSocket connection (e.g. `refresh.js`, a context/hook, or a service module).

---

## 2. WebSocket URL logic (use everywhere the URL is built)

Replace any hardcoded `ws://localhost:8081` with:

**Option A — Next.js (use `NEXT_PUBLIC_OPENCLAW_WS_URL`):**

```ts
function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") return "";
  const envUrl =
    process.env.NEXT_PUBLIC_OPENCLAW_WS_URL ||
    (typeof import.meta !== "undefined" && (import.meta as any).env?.NEXT_PUBLIC_OPENCLAW_WS_URL);
  if (envUrl) return envUrl;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/openclaw/ws`;
}
```

**Option B — Vite (use `VITE_OPENCLAW_WS_URL`):**

```ts
function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") return "";
  const envUrl = import.meta.env.VITE_OPENCLAW_WS_URL;
  if (envUrl) return envUrl;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/openclaw/ws`;
}
```

**Option C — Framework-agnostic (single env name, works in browser only):**

```ts
function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") return "";
  const envUrl = (window as any).__OPENCLAW_WS_URL__;
  if (envUrl) return envUrl;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/openclaw/ws`;
}
```

Use the constructed URL when creating the WebSocket:

```ts
const wsUrl = getOpenClawWsUrl();
const ws = new WebSocket(wsUrl);
```

---

## 3. Backend WebSocket path

- Default same-origin path: **`/openclaw/ws`** (so Nginx can proxy under `/openclaw/`).
- If the OpenClaw backend serves WebSocket at a different path (e.g. `/ws` or `/api/ws`), then:
  - Either keep the frontend using `/openclaw/ws` and configure the backend (or a reverse proxy in the container) to listen at `/openclaw/ws`, or
  - Change the fallback in the code above to the real path, e.g. `${protocol}//${window.location.host}/openclaw/ws` → `${protocol}//${window.location.host}/openclaw/<actual-path>`.

Search the OpenClaw backend/codebase for the WebSocket route (e.g. `"/ws"`, `app.websocket`, `ws://`) and align the path.

---

## 4. basePath / base for production under `/openclaw/`

**Next.js:** In `next.config.js` (or `next.config.mjs`):

```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  basePath: process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || "",
  assetPrefix: process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || undefined,
  // ... rest
};
module.exports = nextConfig;
```

For production build behind `https://dashboard.hilovivo.com/openclaw/` set:

```bash
NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw
```

For local dev (served at `/`), leave unset or set to `""`.

**Vite:** In `vite.config.ts`:

```ts
export default defineConfig({
  base: process.env.VITE_OPENCLAW_BASE_PATH || "/",
  // ...
});
```

For production build under `/openclaw/`:

```bash
VITE_OPENCLAW_BASE_PATH=/openclaw/
```

For local dev, leave unset or set to `"/"`.

Ensure all asset and API requests are relative (e.g. `fetch("/api/...")` becomes `fetch(\`${basePath}/api/...\`)` if you use a basePath variable, or rely on relative paths so they work under `/openclaw/`).

---

## 5. README note (add to OpenClaw frontend repo)

Add a short section, e.g. in `README.md`:

```markdown
## WebSocket URL

- **Production (behind reverse proxy):** The app is served at `https://dashboard.hilovivo.com/openclaw/`. The WebSocket URL defaults to same-origin: `wss://dashboard.hilovivo.com/openclaw/ws`. No env var needed if the backend serves WS at `/ws` and the proxy mounts the app under `/openclaw/`.
- **Override via env (optional):**
  - **Next.js:** `NEXT_PUBLIC_OPENCLAW_WS_URL=wss://example.com/openclaw/ws`
  - **Vite:** `VITE_OPENCLAW_WS_URL=wss://example.com/openclaw/ws`
- **Local dev:** Default is `ws://localhost:<port>/openclaw/ws` if you serve the app at `http://localhost:<port>` with basePath `/openclaw`. For dev at root, you can set the env var to `ws://localhost:8081` (or whatever port the backend uses) so the client connects to the local backend.
```

---

## 6. Diff-style summary (to apply in OpenClaw frontend repo)

| File / area | Change |
|-------------|--------|
| **WebSocket URL** (e.g. `src/config/ws.ts` or where `new WebSocket(...)` is called) | Remove any `ws://localhost:8081`. Add `getOpenClawWsUrl()` using `NEXT_PUBLIC_OPENCLAW_WS_URL` or `VITE_OPENCLAW_WS_URL` and same-origin fallback `\${protocol}//\${host}/openclaw/ws`. Use that function when creating the WebSocket. |
| **Next.js:** `next.config.js` | Add `basePath` and `assetPrefix` from `NEXT_PUBLIC_OPENCLAW_BASE_PATH` (e.g. `/openclaw` for prod). |
| **Vite:** `vite.config.ts` | Set `base` from `VITE_OPENCLAW_BASE_PATH` (e.g. `/openclaw/` for prod). |
| **API/asset paths** | Prefer relative paths or prefix with basePath so they work when app is mounted at `/openclaw/`. |
| **README** | Add "WebSocket URL" section: default same-origin `/openclaw/ws`, optional env override, local dev note. |

---

## Env vars quick reference

| Env var | Framework | Purpose |
|---------|-----------|--------|
| `NEXT_PUBLIC_OPENCLAW_WS_URL` | Next.js | Override WebSocket URL (e.g. `ws://localhost:8081` for local dev). |
| `VITE_OPENCLAW_WS_URL` | Vite | Same. |
| `NEXT_PUBLIC_OPENCLAW_BASE_PATH` | Next.js | e.g. `/openclaw` when served at `https://host/openclaw/`. |
| `VITE_OPENCLAW_BASE_PATH` | Vite | e.g. `/openclaw/` for production build. |

Do **not** change Nginx or dashboard configs in the ATP repo for this; only change the OpenClaw frontend repo.
