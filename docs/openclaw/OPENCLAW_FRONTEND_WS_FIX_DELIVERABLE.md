# OpenClaw frontend — WebSocket URL fix (deliverable)

Use this in the **OpenClaw FRONTEND** repo (builds/publishes `ghcr.io/ccruz0/openclaw`). Not in automated-trading-platform.

**Context:** PROD serves the app at `https://dashboard.hilovivo.com/openclaw/`. Nginx proxies `/openclaw/ws` → LAB:8081 with WebSocket headers. The frontend must not use `ws://localhost:8081`; it must use same-origin `wss://{host}/openclaw/ws` (or `ws://` on http), with optional env override for local dev.

---

## Step A — Detect framework and layout

From the OpenClaw frontend repo root:

- Inspect **package.json**: presence of `"next"` → Next.js; `"vite"` or `"@vitejs/..."` → Vite.
- Inspect **next.config.js** / **next.config.mjs** or **vite.config.ts** / **vite.config.js** to confirm.
- **Source root:** usually `src/` (e.g. `src/lib/`, `src/components/`). If the repo has no `src/`, use `lib/` at root or the existing utils folder.

**Report in 3 bullets:** (1) Framework: Next.js | Vite | other. (2) Config file path. (3) Source root (e.g. `src/`).

---

## Step B — Locate WebSocket creation points

Run from repo root (or use the script below):

```bash
grep -Rn "localhost:8081" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "new WebSocket(" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "ws://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "wss://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "NEXT_PUBLIC_OPENCLAW_WS_URL\|NEXT_PUBLIC_" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . | head -15
grep -Rn "VITE_OPENCLAW_WS_URL\|VITE_" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . | head -15
```

**Or run the script from the OpenClaw repo root:**

```bash
cd /path/to/openclaw-frontend
bash /path/to/automated-trading-platform/scripts/openclaw/openclaw_frontend_ws_apply.sh
```

List every match (file + line) for `localhost:8081`, `new WebSocket(`, `ws://`, `wss://`. Those are the files to change in Step D.

---

## Step C — Implement a single WS URL helper (new file)

**Create:** `src/lib/getOpenClawWsUrl.ts` (or `lib/getOpenClawWsUrl.ts` if there is no `src/`; or reuse the repo’s existing `lib`/`utils` convention).

**Full contents:**

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

- Browser-only: `typeof window === "undefined"` guard.
- Env override first (Next then Vite), then same-origin fallback.

---

## Step D — Replace all hardcoded WS URLs

For **every** place that constructs a WebSocket (from Step B):

1. Add:  
   `import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";`  
   (or `from "../lib/getOpenClawWsUrl"` / your alias).
2. Replace the URL argument with the helper:  
   `new WebSocket(getOpenClawWsUrl())`.
3. Do **not** change handlers, reconnection, or other logic.

**Minimal diff pattern (per file):**

```diff
+ import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";

  const ws = new WebSocket(
-   "ws://localhost:8081"
+   getOpenClawWsUrl()
  );
```

If the hardcoded URL had a path (e.g. `ws://localhost:8081/ws`), still replace the whole URL with `getOpenClawWsUrl()` (the helper uses `/openclaw/ws`).

---

## Step E — Base path support (only if required)

Add only if assets or API calls break when the app is served under `/openclaw/`.

- **Next.js:** In `next.config.js` (or `next.config.mjs`):
  - `basePath: process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || ""`
  - `assetPrefix: basePath || undefined` (or same variable, undefined when empty)
- **Vite:** In `vite.config.ts` (or `vite.config.js`):
  - `base: process.env.VITE_OPENCLAW_BASE_PATH || "/"`

Do not change routing unless necessary.

---

## Step F — Add/update .env.example

Add or merge into `.env.example`:

```bash
# Optional: override WebSocket URL (e.g. local dev). Default: same-origin /openclaw/ws
NEXT_PUBLIC_OPENCLAW_WS_URL=
VITE_OPENCLAW_WS_URL=

# Only if you implemented base path (Step E)
NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw
VITE_OPENCLAW_BASE_PATH=/openclaw/
```

---

## Step G — Verification (must run and show expected outputs)

Run from the OpenClaw frontend repo root **after** applying the patch.

**1) Zero matches for localhost WS:**

```bash
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

**Expected:** No output (exit code 1 is fine).

**2) WebSocket creation and helper usage:**

```bash
grep -Rn "new WebSocket\|getOpenClawWsUrl" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

**Expected:** Each `new WebSocket(` is in a file that also imports and uses `getOpenClawWsUrl()`.

**3) In PROD (browser):**  
DevTools → Network → WS. Load `https://dashboard.hilovivo.com/openclaw/`.  
**Expected:** Request to `wss://dashboard.hilovivo.com/openclaw/ws` with status **101 Switching Protocols**.

---

## Files changed (summary)

| Action | File |
|--------|------|
| **Create** | `src/lib/getOpenClawWsUrl.ts` (or repo’s lib path) |
| **Edit** | Every file that had `new WebSocket("ws://localhost:8081")` or similar: add import, replace URL with `getOpenClawWsUrl()` |
| **Edit (optional)** | `next.config.*` or `vite.config.*` — basePath / base (Step E) |
| **Add/update** | `.env.example` — Step F |

---

## Minimal diffs (per file)

**New file `src/lib/getOpenClawWsUrl.ts`:**  
Use the full contents from Step C above.

**Each file that opened a WebSocket (example):**

```diff
+ import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";

  const ws = new WebSocket(
-   "ws://localhost:8081"
+   getOpenClawWsUrl()
  );
```

**Next.js base path (only if Step E applied):**

```diff
+ const basePath = process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || "";
  module.exports = {
+   basePath: basePath || undefined,
+   assetPrefix: basePath || undefined,
    // ...
  };
```

**Vite base (only if Step E applied):**

```diff
  export default defineConfig({
+   base: process.env.VITE_OPENCLAW_BASE_PATH || "/",
    // ...
  });
```

---

## Verification command outputs (expected)

**After patch, from OpenClaw repo root:**

```bash
# 1) Must be zero matches
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
# Expected: (no output)

# 2) WebSocket and helper
grep -Rn "new WebSocket\|getOpenClawWsUrl" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
# Expected: e.g.
# src/foo.ts:12:  const ws = new WebSocket(getOpenClawWsUrl());
# src/foo.ts:3: import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";
```

**Browser:** Network → WS → `wss://dashboard.hilovivo.com/openclaw/ws` → **101**.
