# Cursor prompt — run inside the OpenClaw frontend repo

**Use this in:** The OpenClaw FRONTEND repo that builds `ghcr.io/ccruz0/openclaw`.  
**Do not run in ATP.** Open that repo in Cursor, then paste the prompt below into the chat.

---

## Prompt (copy everything below this line)

```
CURSOR PROMPT (run this inside the OpenClaw frontend repo that builds `ghcr.io/ccruz0/openclaw`)

You are working in the OpenClaw FRONTEND repo (not ATP). The app is served in production at:
https://dashboard.hilovivo.com/openclaw/
Nginx proxies the WebSocket at:
wss://dashboard.hilovivo.com/openclaw/ws   (same-origin)

Task
1) Remove any hardcoded WebSocket URLs like `ws://localhost:8081` or any fixed host/port.
2) Make the WebSocket use env override for local dev only, else same-origin:
   `${proto}//${location.host}/openclaw/ws`
3) Ensure the frontend works when hosted under the base path `/openclaw/` (assets + routing).
4) Output a minimal diff + verification commands.

Step A — Detect framework + locate WS usage
- Inspect package.json scripts and config files to decide: Next.js or Vite.
- Run and paste results into your response:
  - `grep -Rn "localhost:8081\|ws://localhost\|127\.0\.0\.1" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .`
  - `grep -Rn "new WebSocket\|WebSocket(" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .`
  - `grep -Rn "WS_URL\|SOCKET\|NEXT_PUBLIC\|VITE_" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .`

Step B — Add a single helper (source of truth)
Create a new file:
- If repo uses `src/` then `src/lib/getOpenClawWsUrl.ts`
- Else place it in the closest existing lib/utils folder and match the project's import style.

File contents (copy exactly, TypeScript):

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

Step C — Replace WS creation everywhere
For every place that opens a WebSocket (directly or via a client wrapper):
- Replace any string URL with `getOpenClawWsUrl()`
Examples:
- `new WebSocket("ws://localhost:8081")` -> `new WebSocket(getOpenClawWsUrl())`
- `createClient({ url: "ws://localhost:8081" })` -> `createClient({ url: getOpenClawWsUrl() })`
- If code appends paths, keep it consistent with WS_PATH or refactor so the helper returns the full correct URL.

Do NOT introduce `ws://localhost` anywhere (even as "temporary").

Step D — Base path support (/openclaw/)
If Next.js:
- Update next.config.(js|mjs|ts):
  - basePath from env: `NEXT_PUBLIC_OPENCLAW_BASE_PATH` default ""
  - assetPrefix should align with basePath
- Ensure any fetch/asset path uses relative paths or respects basePath.

If Vite:
- Update vite.config.(ts|js):
  - `base: process.env.VITE_OPENCLAW_BASE_PATH || "/"`

Add/extend `.env.example` (do not hardcode localhost in code):
NEXT_PUBLIC_OPENCLAW_WS_URL=
VITE_OPENCLAW_WS_URL=
NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw
VITE_OPENCLAW_BASE_PATH=/openclaw/

Step E — Verification (must pass)
1) No localhost WebSockets in app source:
grep -Rn "localhost:8081\|ws://localhost\|127\.0\.0\.1" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
Expected: no matches.

2) WS uses helper:
grep -Rn "getOpenClawWsUrl\|new WebSocket" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
Expected: WebSocket creation points to getOpenClawWsUrl().

Step F — Output required from you
In your final response include:
- The exact list of files changed
- A minimal diff for each change
- The verification command outputs (or note "no matches")
- Any assumptions you had to make about framework/import paths

Acceptance
In production browser devtools:
- WebSocket connects to `wss://dashboard.hilovivo.com/openclaw/ws`
- Response status is 101 Switching Protocols
- No "ws://localhost:8081" appears in console/network
- App works under `/openclaw/` without broken assets or routing
```

---

## Prompt variant 2 (short — copy from here)

```
CURSOR PROMPT (paste this in Cursor with the OPENCLAW FRONTEND repo open)

Context
- You are in the OpenClaw frontend repo (this is NOT the ATP repo).
- Production serves the app under: https://dashboard.hilovivo.com/openclaw/
- Nginx proxies the WebSocket at: /openclaw/ws (same origin).
- Goal: remove any hardcoded `ws://localhost:8081` (or any fixed host/port) and make WS same-origin + base-path safe.

What to do
1) Identify framework (Next.js vs Vite)
- Check `package.json` scripts and presence of `next.config.*` or `vite.config.*`.
- State which one it is in your response.

2) Find all WebSocket URL sources
Run and include outputs (paths + lines) in your response:
- grep -Rn "localhost:8081|ws://localhost|127\.0\.0\.1" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
- grep -Rn "new WebSocket\(|WebSocket\(" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
- grep -Rn "WS_URL|SOCKET|NEXT_PUBLIC|VITE_" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .

3) Add a single helper: getOpenClawWsUrl()
Create `src/lib/getOpenClawWsUrl.ts` (or the closest existing `lib/` or `utils/` folder used by the repo) with EXACT content:

const WS_PATH = "/openclaw/ws";

export function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") return "";

  const nextEnv =
    typeof process !== "undefined" && process.env?.NEXT_PUBLIC_OPENCLAW_WS_URL;
  if (nextEnv) return nextEnv;

  const viteEnv =
    typeof import.meta !== "undefined" &&
    (import.meta as unknown as { env?: { VITE_OPENCLAW_WS_URL?: string } }).env
      ?.VITE_OPENCLAW_WS_URL;
  if (viteEnv) return viteEnv;

  const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${wsProto}//${window.location.host}${WS_PATH}`;
}

Rules
- Do NOT hardcode `ws://localhost` anywhere in code (even "temporary").
- Local dev overrides only via env vars above.

4) Replace all WebSocket usage
Everywhere you see:
- new WebSocket("ws://localhost:8081...") or any fixed host/port
Replace with:
- new WebSocket(getOpenClawWsUrl())
If the repo uses a client factory like `createClient({ url })`, update it to:
- createClient({ url: getOpenClawWsUrl() })

5) Base path support for /openclaw/
If Next.js:
- Update `next.config.*` to use:
  - basePath from `NEXT_PUBLIC_OPENCLAW_BASE_PATH || ""`
  - assetPrefix aligned with basePath
If Vite:
- Update `vite.config.*` to use:
  - base: process.env.VITE_OPENCLAW_BASE_PATH || "/"

6) Update `.env.example`
Add (or ensure present):
NEXT_PUBLIC_OPENCLAW_WS_URL=
VITE_OPENCLAW_WS_URL=
NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw
VITE_OPENCLAW_BASE_PATH=/openclaw/

7) Verification (must pass)
Run and show outputs:
- grep -Rn "localhost:8081|ws://localhost|127\.0\.0\.1" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
  Expected: no matches.
- grep -Rn "getOpenClawWsUrl|new WebSocket" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
  Expected: WS creation uses getOpenClawWsUrl().

Deliverable
- Provide a minimal diff for all changes.
- List all files changed.
- Confirm the WS URL is now same-origin and compatible with hosting under `/openclaw/`.

Acceptance target (what production should show)
- Browser Network WS connects to: wss://dashboard.hilovivo.com/openclaw/ws
- Status: 101 Switching Protocols
- No console error referencing ws://localhost:8081
- No broken assets or routing under /openclaw/
```

---

## Prompt variant 3 (non-negotiables + deliverable)

```
You are working in the OpenClaw FRONTEND repo (the one that builds/pushes ghcr.io/ccruz0/openclaw). Goal: fix production WebSocket + base path so https://dashboard.hilovivo.com/openclaw/ works and the browser does NOT try ws://localhost:8081.

Non-negotiables
- Do not hardcode ws://localhost, 127.0.0.1, fixed ports, or fixed hosts in frontend code.
- Production WebSocket must be SAME-ORIGIN behind nginx:
  - Page: https://dashboard.hilovivo.com/openclaw/
  - WS: wss://dashboard.hilovivo.com/openclaw/ws
- Local dev override is allowed ONLY via env var.

Step 1 — Identify framework
- Inspect package.json + config files and determine if this repo is Next.js or Vite (or something else).
- Write in your output: "Framework = Next.js" or "Framework = Vite" and the evidence (file names / scripts).

Step 2 — Find all WebSocket usage and any hardcoded localhost
Run searches and report results as a list of exact matches (file:line + snippet):
- localhost:8081, ws://localhost, 127.0.0.1
- new WebSocket(
- any WS URL config: WS_URL, SOCKET, NEXT_PUBLIC, VITE_

Use these commands (or equivalent):
- grep -RnE "localhost:8081|ws://localhost|127\.0\.0\.1" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
- grep -RnE "new WebSocket\(" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
- grep -RnE "WS_URL|SOCKET|NEXT_PUBLIC|VITE_" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .

Step 3 — Add a single WS URL helper (source of truth)
Create: src/lib/getOpenClawWsUrl.ts (adjust path if this repo uses a different src/ layout, but keep the name).
Content must be exactly this (no extra logic, keep it simple):

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

Rules:
- No fixed host/port.
- Env override first (NEXT_PUBLIC_OPENCLAW_WS_URL for Next, VITE_OPENCLAW_WS_URL for Vite).
- Fallback derives from location and uses /openclaw/ws.

Step 4 — Replace every WebSocket creation to use the helper
For every place that creates a WebSocket (or passes a WS URL into a client like createClient({ url }), etc):
- Remove hardcoded ws://localhost:8081 (or any string host/port)
- Import the helper and use getOpenClawWsUrl()

Example replacement pattern:
- import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl"; (adjust alias/path to match repo)
- const ws = new WebSocket(getOpenClawWsUrl());

If this repo uses a different alias than @/:
- Use the repo's existing import style. If no alias, use relative import.

Step 5 — Base path support for /openclaw/
Production serves the app under /openclaw/ (not /). Fix routing/assets so it works.

If Next.js:
- Update next.config.* to use:
  - const basePath = process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || "";
  - basePath
  - assetPrefix: basePath || undefined
- Ensure any absolute fetch/asset paths are compatible with basePath (prefer relative paths or prefix with basePath).

If Vite:
- Update vite.config.* to use:
  - base: process.env.VITE_OPENCLAW_BASE_PATH || "/"
- Ensure asset paths work under /openclaw/.

Step 6 — Env examples
Add or update .env.example (or docs) with:
NEXT_PUBLIC_OPENCLAW_WS_URL=
VITE_OPENCLAW_WS_URL=
NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw
VITE_OPENCLAW_BASE_PATH=/openclaw/

Notes:
- In production, WS env can be empty (same-origin fallback).
- Local dev can set WS env to whatever local WS endpoint you use.

Step 7 — Verification (must be clean)
After edits, run and report outputs:
1) Must have ZERO matches:
- grep -RnE "localhost:8081|ws://localhost|127\.0\.0\.1" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .
2) Show where WS is created now:
- grep -RnE "new WebSocket\(|getOpenClawWsUrl" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" .

Deliverable in your response
- List of files changed (exact paths).
- Minimal diff summary (what changed where).
- The exact verification outputs (or a clear statement: "grep returned no matches" for step 7.1).
- Any remaining risks you see (ex: backend WS path mismatch), with a concrete fix.

Acceptance target
- In production browser console, there is NO ws://localhost:8081.
- WebSocket connects to wss://dashboard.hilovivo.com/openclaw/ws and gets 101 Switching Protocols.
- App assets and routes work under /openclaw/ without 404s.
```
