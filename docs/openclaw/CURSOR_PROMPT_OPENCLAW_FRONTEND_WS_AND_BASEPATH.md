# Cursor prompt: OpenClaw frontend — fix WebSocket and /openclaw base path

**Use this prompt in the OpenClaw FRONTEND repo** (the repo that builds `ghcr.io/ccruz0/openclaw`).  
Open that repo in Cursor, then paste the prompt below (or the steps) and run.

---

## Prompt (copy into Cursor in the OpenClaw frontend repo)

```
You are working in the OpenClaw FRONTEND repository (the repo that builds ghcr.io/ccruz0/openclaw).

Goal
Make the app work behind an Nginx reverse proxy mounted at:
https://dashboard.hilovivo.com/openclaw/

Fix these issues:
• Remove any hardcoded "ws://localhost:8081".
• WebSocket must work behind reverse proxy using same-origin.
• Support running under base path /openclaw.
• Keep local development working.

Do the following steps carefully.

------------------------------------------------
1. Find all WebSocket references
------------------------------------------------

Search the entire repo for:
localhost:8081
WebSocket(
ws://
wss://
SOCKET
WS_URL
NEXT_PUBLIC
VITE_

List every match with file path and line number.

------------------------------------------------
2. Create a single WebSocket helper
------------------------------------------------

Create a new file:
src/lib/getOpenClawWsUrl.ts

Contents:

const WS_PATH = "/openclaw/ws";

export function getOpenClawWsUrl(): string {
  if (typeof window === "undefined") return "";

  const nextEnv =
    typeof process !== "undefined" &&
    process.env?.NEXT_PUBLIC_OPENCLAW_WS_URL;

  if (nextEnv) return nextEnv;

  const viteEnv =
    typeof import.meta !== "undefined" &&
    (import.meta as any)?.env?.VITE_OPENCLAW_WS_URL;

  if (viteEnv) return viteEnv;

  const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";

  return `${wsProto}//${window.location.host}${WS_PATH}`;
}

------------------------------------------------
3. Replace hardcoded WebSocket URLs
------------------------------------------------

Replace every instance like:
new WebSocket("ws://localhost:8081")
or similar with:

import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl";
const ws = new WebSocket(getOpenClawWsUrl());

Do not leave any localhost WebSocket URLs in the codebase.

------------------------------------------------
4. Support running under /openclaw
------------------------------------------------

Detect the framework.

If the project uses Next.js:
Edit next.config.js:
const basePath = process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || "";
module.exports = {
  basePath,
  assetPrefix: basePath || undefined,
};

If the project uses Vite:
Edit vite.config.ts:
export default defineConfig({
  base: process.env.VITE_OPENCLAW_BASE_PATH || "/",
});

------------------------------------------------
5. Ensure API and asset paths work under /openclaw
------------------------------------------------

Search for:
fetch("/api
axios("/api
"/static
"/assets

Replace absolute paths with basePath + "/api/..." or relative paths.
The app must function when served from /openclaw/.

------------------------------------------------
6. Add environment variable support
------------------------------------------------

Add .env.example:

NEXT_PUBLIC_OPENCLAW_WS_URL=
NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw

VITE_OPENCLAW_WS_URL=
VITE_OPENCLAW_BASE_PATH=/openclaw/

------------------------------------------------
7. Output
------------------------------------------------

Provide:
• list of files changed
• minimal diff
• confirmation no localhost websocket URLs remain
```

---

## After running in OpenClaw repo: expected output shape

Once you run the prompt in the **OpenClaw frontend repo**, the agent there should produce something like:

**Files changed (example):**
- `src/lib/getOpenClawWsUrl.ts` (new)
- `src/.../refresh.js` or wherever `new WebSocket("ws://localhost:8081")` was (edited)
- `next.config.js` or `vite.config.ts` (edited)
- `.env.example` (new or updated)

**Confirmation:** Grep for `localhost:8081` and `ws://` in `*.{js,ts,tsx,jsx,vue}` → no matches.

**Acceptance:** Build with `NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw` (or Vite equivalent), deploy; at https://dashboard.hilovivo.com/openclaw/ the console must not show `ws://localhost:8081`, and the Network tab must show WebSocket to `wss://dashboard.hilovivo.com/openclaw/ws` with status 101.
