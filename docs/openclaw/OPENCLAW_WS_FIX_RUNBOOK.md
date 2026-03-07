# OpenClaw WebSocket fix — run in the OpenClaw frontend repo (not ATP)

**Workspace:** You must be in the repo that builds/pushes `ghcr.io/ccruz0/openclaw`. This runbook is for use **there**, not in `automated-trading-platform`.

**Goal:** Remove hardcoded `ws://localhost...`, use same-origin in prod (`wss://dashboard.hilovivo.com/openclaw/ws`), keep local dev override only via env vars.

---

## Step 1 — Open the correct repo in Cursor

- Repo: the one that builds/pushes **`ghcr.io/ccruz0/openclaw`**
- Not the ATP repo

---

## Step 2 — Run these searches and paste the full output

In the **OpenClaw frontend repo root**:

```bash
cd <OPENCLAW_FRONTEND_REPO>

grep -Rn "localhost:8081\|ws://localhost\|127\.0\.0\.1" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .

grep -Rn "new WebSocket" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .

grep -Rn "WS_URL\|WSS\|SOCKET\|NEXT_PUBLIC\|VITE_" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
```

Also run:

```bash
cat package.json | head -40
```

**Paste back:** The full grep output + the package.json snippet. And say whether the app is **Next.js** or **Vite** (from package.json scripts/deps). With that, an exact diff can be generated.

---

## Step 3 — Implement the fix

### 3A — Create `src/lib/getOpenClawWsUrl.ts`

If the repo has no `src/lib`, use the closest equivalent (`lib/`, `utils/`, etc.) and adjust the path in 3B.

**Create this file with exactly this content:**

```ts
const WS_PATH = "/openclaw/ws";

export function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") return "";

  // Next.js override (local dev)
  const nextEnv =
    typeof process !== "undefined" && process.env?.NEXT_PUBLIC_OPENCLAW_WS_URL;
  if (nextEnv) return nextEnv;

  // Vite override (local dev)
  const viteEnv =
    typeof import.meta !== "undefined" &&
    (import.meta as unknown as { env?: { VITE_OPENCLAW_WS_URL?: string } }).env
      ?.VITE_OPENCLAW_WS_URL;
  if (viteEnv) return viteEnv;

  // Same-origin fallback (prod + safe default)
  const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${wsProto}//${window.location.host}${WS_PATH}`;
}
```

### 3B — Replace every hardcoded WebSocket URL

Find code like:

- `new WebSocket("ws://localhost:8081")`
- `new WebSocket("ws://localhost:8081/")`
- `new WebSocket(SOME_URL_THAT_INCLUDES_LOCALHOST)`

Replace with:

```ts
import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";
// ...
const ws = new WebSocket(getOpenClawWsUrl());
```

- If the repo does **not** use `@/`, use the repo’s import style (e.g. `from "../lib/getOpenClawWsUrl"` or `from "lib/getOpenClawWsUrl"`).

If you use a wrapper, e.g.:

- `createClient({ url: "ws://localhost:8081" })`  
  Change to: `createClient({ url: getOpenClawWsUrl() })`

---

## Step 4 — Update env examples (no localhost in code)

Add to **`.env.example`** (or create it if missing):

```bash
NEXT_PUBLIC_OPENCLAW_WS_URL=
VITE_OPENCLAW_WS_URL=
```

**Rule:** Only local dev uses these env overrides. Prod uses the same-origin fallback automatically.

---

## Step 5 — Verify (must be clean)

These must return **no matches**:

```bash
grep -Rn "localhost:8081\|ws://localhost\|127\.0\.0\.1" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
```

Confirm the helper is used:

```bash
grep -Rn "getOpenClawWsUrl" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
```

---

## Step 6 — Build + push + deploy

- Build and push the OpenClaw image to `ghcr.io/ccruz0/openclaw:<tag>`
- On LAB: `docker compose pull` / `up` for the OpenClaw service (your repo’s normal flow)

---

## Step 7 — Acceptance test

1. Open: **https://dashboard.hilovivo.com/openclaw/**
2. DevTools → **Network** → **WS**
3. **WebSocket URL must be:** `wss://dashboard.hilovivo.com/openclaw/ws`
4. **Status:** 101 Switching Protocols

---

## What to paste back (so an exact diff can be generated)

When you run this in the OpenClaw repo, paste back:

1. **Grep matches** from Step 2 (all three grep commands’ output) — file paths + line numbers.
2. **Framework:** Next.js or Vite (from `package.json` scripts/deps).

With that, an exact file-by-file diff can be generated for you to apply in the OpenClaw repo.
