# Apply in OpenClaw frontend repo — WS URL + base path

Use this when you are in the **OpenClaw frontend repository** (the one that builds/pushes `ghcr.io/ccruz0/openclaw`). Production is served at `https://dashboard.hilovivo.com/openclaw/`; Nginx proxies `/openclaw/ws` → LAB:8081 with WebSocket headers.

**Goal:** Never use `ws://localhost:8081` in prod; use same-origin `(wss|ws)://{host}/openclaw/ws` by default; allow env override for local dev. Minimal changes.

---

## Step 1: Identify framework

From the repo root:

```bash
cat package.json | grep -E '"next"|"vite"|"@vitejs'  # or inspect next.config.js / vite.config.*
```

- **Next.js** if you have `next`, `next.config.js` (or `next.config.mjs`).
- **Vite** if you have `vite`, `vite.config.ts` (or `vite.config.js`).

Note the framework; it determines which env vars and config you edit below.

---

## Step 2: Find WS usage

Run (from repo root):

```bash
echo "=== localhost:8081 ==="
grep -Rn "localhost:8081" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true

echo "=== new WebSocket( ==="
grep -Rn "new WebSocket(" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true

echo "=== ws:// ==="
grep -Rn "ws://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true

echo "=== wss:// ==="
grep -Rn "wss://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true

echo "=== NEXT_PUBLIC (first 15) ==="
grep -Rn "NEXT_PUBLIC" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null | head -15

echo "=== VITE_ (first 15) ==="
grep -Rn "VITE_" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null | head -15
```

List every match (file + line) for `localhost:8081`, `new WebSocket(`, `ws://`, `wss://`. Use these to know where to add the helper and replace the URL.

---

## Step 3: Add a single WS URL helper

Create **one** file (adjust path if your app uses a different `src` layout):

**File:** `src/lib/getOpenClawWsUrl.ts`

```ts
/**
 * WebSocket URL for OpenClaw. Production: same-origin /openclaw/ws.
 * Override via NEXT_PUBLIC_OPENCLAW_WS_URL (Next) or VITE_OPENCLAW_WS_URL (Vite) for local dev.
 */
const WS_PATH = "/openclaw/ws";

export function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") return "";

  const nextEnv =
    typeof process !== "undefined" && process.env?.NEXT_PUBLIC_OPENCLAW_WS_URL;
  if (nextEnv) return nextEnv;

  const viteEnv =
    typeof import.meta !== "undefined" &&
    (import.meta as { env?: { VITE_OPENCLAW_WS_URL?: string } })?.env
      ?.VITE_OPENCLAW_WS_URL;
  if (viteEnv) return viteEnv;

  const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${wsProto}//${window.location.host}${WS_PATH}`;
}
```

---

## Step 4: Replace hardcoded WS URL(s)

For **each** place that opens a WebSocket (from Step 2):

1. Add: `import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";` (or your alias, e.g. `@/lib/getOpenClawWsUrl` or relative path).
2. Replace e.g. `new WebSocket("ws://localhost:8081")` or `new WebSocket(someUrl)` when `someUrl` is localhost:8081 with:

   `new WebSocket(getOpenClawWsUrl())`

Keep all other behavior (message handlers, reconnection, etc.) unchanged.

**Example minimal diff:**

```diff
+ import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";

  const ws = new WebSocket(
-   "ws://localhost:8081"
+   getOpenClawWsUrl()
  );
```

---

## Step 5: Base path (only if needed)

Only if the app is served under `/openclaw/` and you see broken absolute paths or the project already has basePath/base support:

- **Next.js:** In `next.config.js` (or `next.config.mjs`):

```diff
+ const basePath = process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || "";
  module.exports = {
+   basePath: basePath || undefined,
+   assetPrefix: basePath || undefined,
    // ... rest
  };
```

- **Vite:** In `vite.config.ts` (or `vite.config.js`):

```diff
  export default defineConfig({
+   base: process.env.VITE_OPENCLAW_BASE_PATH || "/",
    // ... rest
  });
```

If the app already works under `/openclaw/` with relative paths, you can skip this.

---

## Step 6: Env examples

Add or update `.env.example`:

```bash
# Optional: override WebSocket URL (e.g. local dev). Default: same-origin /openclaw/ws
NEXT_PUBLIC_OPENCLAW_WS_URL=
# Vite:
# VITE_OPENCLAW_WS_URL=

# Base path when served at /openclaw/ (Next.js)
NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw
# Vite
VITE_OPENCLAW_BASE_PATH=/openclaw/
```

---

## Step 7: Verification

**1) Zero matches for localhost WS:**

```bash
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
# Expected: no output (exit 1 is OK).
```

**2) Where WebSocket is created and helper import:**

```bash
grep -Rn "new WebSocket\|getOpenClawWsUrl" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
# Expected: each WebSocket creation uses getOpenClawWsUrl() and file imports the helper.
```

**3) In browser (production or staging):**

- Open DevTools → Network → WS.
- Load the app from `https://dashboard.hilovivo.com/openclaw/`.
- WebSocket request URL: `wss://dashboard.hilovivo.com/openclaw/ws`.
- Status: **101 Switching Protocols**.

---

## Files changed (summary)

| Action | File |
|--------|------|
| Create | `src/lib/getOpenClawWsUrl.ts` |
| Edit | Every file that had `new WebSocket("ws://localhost:8081")` or similar: add import, replace URL with `getOpenClawWsUrl()` |
| Edit (if needed) | `next.config.js` or `vite.config.*` — basePath / base |
| Add/update | `.env.example` — WS URL and base path vars |

Reference implementation (helper + config examples) lives in this repo under `docs/openclaw/reference-frontend/`.
