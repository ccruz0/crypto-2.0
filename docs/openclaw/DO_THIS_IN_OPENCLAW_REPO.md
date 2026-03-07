# OpenClaw WebSocket fix — do this in the OpenClaw frontend repo

**Use this in:** The repo that builds `ghcr.io/ccruz0/openclaw` (OpenClaw frontend).  
**Goal:** Remove hardcoded `ws://localhost:8081`, use same-origin `/openclaw/ws`, keep local dev via env.

Open that repo in Cursor (or a terminal) and follow the steps below. All code is copy-paste ready.

---

## Step 1 — Find what to change

In the **OpenClaw frontend repo root**, run:

```bash
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "new WebSocket(" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

Note every **file:line** that has a hardcoded `ws://` URL or `new WebSocket("ws://...")`. You will add the helper and replace the URL in those files.

---

## Step 2 — Add the helper (new file)

Create this file (create the directory if needed):

**Path:** `src/lib/getOpenClawWsUrl.ts`  
(or `lib/getOpenClawWsUrl.ts` if the repo has no `src/`)

**Contents (paste as-is):**

```ts
/**
 * WebSocket URL for OpenClaw. PROD: same-origin /openclaw/ws.
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

  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${WS_PATH}`;
}
```

---

## Step 3 — Replace WebSocket usage

In **every file** that had `new WebSocket("ws://localhost:8081...")` or similar (from Step 1):

1. **Add import** at the top (use the path/alias your repo uses, e.g. `@/lib` or `../lib`):

   ```ts
   import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";
   ```

2. **Replace the URL** where the WebSocket is created:

   - Change: `new WebSocket("ws://localhost:8081/")` (or whatever the hardcoded URL was)  
   - To: `new WebSocket(getOpenClawWsUrl())`

   Do **not** change handlers, reconnect logic, or anything else.

**If the app uses a gateway that takes `opts.url`** (e.g. `createGatewayClient({ url: "ws://...", ... })`): where you build that options object, set `url: getOpenClawWsUrl()` instead of the hardcoded string.

---

## Step 4 — .env.example

Add or ensure these lines exist (empty = prod uses same-origin; set only for local dev):

```bash
# Optional: override WebSocket URL. Default: same-origin /openclaw/ws (prod).
NEXT_PUBLIC_OPENCLAW_WS_URL=
VITE_OPENCLAW_WS_URL=
```

---

## Step 5 — Verify

In the OpenClaw frontend repo root:

```bash
# Must be no output:
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .

# Should show your edited files and the helper:
grep -Rn "new WebSocket\|getOpenClawWsUrl" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

---

## Step 6 — Build and deploy

1. **Build** the OpenClaw image (same way you usually do, e.g. Docker build for `ghcr.io/ccruz0/openclaw`).
2. **Push** the image to your registry.
3. **On LAB:** pull the new image and restart the OpenClaw container (e.g. `docker compose` or your runbook).

Then in the browser: open https://dashboard.hilovivo.com/openclaw/ and check the console. You should see a WebSocket connection to `wss://dashboard.hilovivo.com/openclaw/ws` (status 101), not `ws://localhost:8081`.

---

**Summary:** Add `getOpenClawWsUrl.ts`, replace every hardcoded OpenClaw WS URL with `getOpenClawWsUrl()`, add env vars to `.env.example`, verify with greps, then build/push/deploy.
