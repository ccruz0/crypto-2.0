# OpenClaw frontend — WebSocket fix (apply in OpenClaw repo)

**Where to apply:** The repo that builds `ghcr.io/ccruz0/openclaw` (OpenClaw frontend). Not in automated-trading-platform.

**Goal:** Remove hardcoded `ws://localhost:8081`. Default to same-origin `/openclaw/ws`. Keep local dev via env override.

---

## Step 1 — Find every reference (run in OpenClaw frontend repo root)

```bash
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "new WebSocket(" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

List each match: **file path + line number**. Those files get the replacement in Step 3.

---

## Step 2 — Add helper

**Create:** `src/lib/getOpenClawWsUrl.ts` (or `lib/getOpenClawWsUrl.ts` if the repo has no `src/`).

Copy the full contents from this repo:

**`docs/openclaw/reference-frontend/src/lib/getOpenClawWsUrl.ts`**

Or paste:

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

## Step 3 — Replace WebSocket creation

In **every file** that had `new WebSocket("ws://localhost:8081...")` or similar:

1. Add at top (adjust path/alias to your repo):
   ```ts
   import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";
   ```
   or
   ```ts
   import { getOpenClawWsUrl } from "../lib/getOpenClawWsUrl";
   ```

2. Replace the URL with the helper:
   ```diff
   - new WebSocket("ws://localhost:8081/")
   + new WebSocket(getOpenClawWsUrl())
   ```
   Keep all handlers, reconnect logic, and other code unchanged.

---

## Step 4 — Add/update .env.example

Ensure these exist (values empty for prod; set for local dev):

```bash
# Optional: override WebSocket URL. Default: same-origin /openclaw/ws (prod).
NEXT_PUBLIC_OPENCLAW_WS_URL=
VITE_OPENCLAW_WS_URL=
```

Full reference: `docs/openclaw/reference-frontend/.env.example` in the ATP repo.

---

## Step 5 — Verification (run in OpenClaw frontend repo root)

**1) Must be zero matches:**

```bash
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

**Expected:** No output (exit code 1 is fine).

**2) WebSocket usage now:**

```bash
grep -Rn "new WebSocket\|getOpenClawWsUrl" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

**Expected:** Each `new WebSocket(` is in a file that also uses `getOpenClawWsUrl()`.

---

## Files changed (summary)

| Action | File |
|--------|------|
| **Create** | `src/lib/getOpenClawWsUrl.ts` (or repo’s lib path) |
| **Edit** | Every file that had `new WebSocket("ws://localhost:8081...")`: add import, replace URL with `getOpenClawWsUrl()` |
| **Add/update** | `.env.example`: `NEXT_PUBLIC_OPENCLAW_WS_URL=`, `VITE_OPENCLAW_WS_URL=` |

---

## Minimal diffs (per file)

**New file `src/lib/getOpenClawWsUrl.ts`:**  
Use the full contents from Step 2.

**Each file that opened a WebSocket:**

```diff
+ import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";

  const ws = new WebSocket(
-   "ws://localhost:8081/"
+   getOpenClawWsUrl()
  );
```

(If the alias is different, use e.g. `from "../lib/getOpenClawWsUrl"`.)

**If your app uses a gateway that takes `opts.url`** (e.g. `createGatewayClient({ url: "...", ... })`): where you build the options, pass `url: getOpenClawWsUrl()` instead of a hardcoded `ws://localhost:8081` (or similar).

---

## Grep outputs (paste after applying in OpenClaw repo)

Run in **OpenClaw frontend repo root** after the fix:

```bash
# 1) Zero localhost WS
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

Paste output (should be empty).

```bash
# 2) WebSocket and helper
grep -Rn "new WebSocket\|getOpenClawWsUrl" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

Paste output (should show the edited files and the new helper).
