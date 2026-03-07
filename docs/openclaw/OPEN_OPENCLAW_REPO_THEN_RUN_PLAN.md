# Open the OpenClaw frontend repo first, then run the WebSocket + base path plan

You are currently in **automated-trading-platform (ATP)**. The OpenClaw app (the one that builds/pushes `ghcr.io/ccruz0/openclaw`) is a **different repo**.

---

## Action now

### 1. In Cursor: File → Open Folder…

Select the **OpenClaw FRONTEND** repo folder (the one that builds/pushes `ghcr.io/ccruz0/openclaw`).

### 2. Confirm it’s the right repo

- There is a **package.json at the repo root**
- You can find WebSocket code (`new WebSocket(...)`) or references to `ws://localhost:8081`

### 3. Run the plan below in that repo

Paste the plan (Steps 1–7) into Cursor **with the OpenClaw frontend repo open**, or follow the steps manually.

---

## Plan (run in OpenClaw frontend repo)

**Goal**
- Production OpenClaw: https://dashboard.hilovivo.com/openclaw/
- Browser must NOT use `ws://localhost:8081`
- WebSocket: same-origin `wss://dashboard.hilovivo.com/openclaw/ws`
- Base path works under `/openclaw/` (no 404 assets)

**Non-negotiables**
- No hardcoded `ws://localhost`, `127.0.0.1`, fixed host, or fixed port in frontend code.
- Local dev override only via env var.

---

### Step 1 — Identify framework (Next.js vs Vite)

- Check `package.json` scripts and presence of `next.config.*` or `vite.config.*`.
- Output: “Framework = Next.js” or “Framework = Vite” + evidence.

---

### Step 2 — Find all WS usage + hardcoded localhost

Run in repo root:

```bash
grep -RnE "localhost:8081|ws://localhost|127\.0\.0\.1" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
grep -RnE "new WebSocket\(" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
grep -RnE "WS_URL|SOCKET|NEXT_PUBLIC|VITE_" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
```

Paste results (file:line + snippet).

---

### Step 3 — Add WS URL helper (single source of truth)

Create **`src/lib/getOpenClawWsUrl.ts`** (adjust `src/` path if the repo uses a different structure; keep the filename).

**EXACT content:**

```ts
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

### Step 4 — Replace ALL WebSocket URL usage

- Replace any hardcoded `ws://...` strings with `getOpenClawWsUrl()`.
- Update any `createClient({ url: ... })` or equivalent.
- Import the helper using the repo’s style (`@/lib/...` if present, else relative).

Examples:
- `const ws = new WebSocket(getOpenClawWsUrl());`
- `createClient({ url: getOpenClawWsUrl() })`

---

### Step 5 — Base path support (/openclaw/)

**If Next.js:** in `next.config.*` add:

```js
const basePath = process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || "";
module.exports = { basePath, assetPrefix: basePath || undefined, ... };
```

**If Vite:** in `vite.config.*` add:

```js
base: process.env.VITE_OPENCLAW_BASE_PATH || "/"
```

---

### Step 6 — .env.example

Add or ensure present:

```
NEXT_PUBLIC_OPENCLAW_WS_URL=
VITE_OPENCLAW_WS_URL=
NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw
VITE_OPENCLAW_BASE_PATH=/openclaw/
```

---

### Step 7 — Verify (must be clean)

1. **Zero matches** (run in repo root):

```bash
grep -RnE "localhost:8081|ws://localhost|127\.0\.0\.1" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
```
Expected: no output.

2. **WS creation sites** (should use helper):

```bash
grep -RnE "new WebSocket\(|getOpenClawWsUrl" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
```
Expected: all WebSocket creation uses `getOpenClawWsUrl()`.

---

## Deliverable (when done)

- List of files changed (exact paths).
- Minimal diff summary (what changed where).
- Verification outputs (or “no matches” for step 7.1).
- Any remaining risk (e.g. backend WS path mismatch) + concrete fix.

---

## Acceptance

- No `ws://localhost:8081` in browser console.
- WebSocket connects to `wss://dashboard.hilovivo.com/openclaw/ws` with **101 Switching Protocols**.
- App works under `/openclaw/` with no asset 404s.
