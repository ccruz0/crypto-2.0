# OpenClaw frontend reference (copy into OpenClaw repo)

Copy these files into the **OpenClaw frontend repo** (the one that builds `ghcr.io/ccruz0/openclaw`).

## 1. WebSocket URL helper

- Copy `src/lib/getOpenClawWsUrl.ts` into your repo (same path or adjust imports).
- Where you currently have `new WebSocket("ws://localhost:8081")` or similar, replace with:

```ts
import { getOpenClawWsUrl } from "@/lib/getOpenClawWsUrl"; // or your path

const ws = new WebSocket(getOpenClawWsUrl());
```

## 2. Base path (choose one)

- **Next.js:** Merge `next.config.example.js` into your `next.config.js` (basePath + assetPrefix from `NEXT_PUBLIC_OPENCLAW_BASE_PATH`).
- **Vite:** Merge `vite.config.example.ts` into your `vite.config.*` (base from `VITE_OPENCLAW_BASE_PATH`).

## 3. Env vars

Use `.env.example` as reference. For prod (behind Nginx at `/openclaw/`):

- `NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw` (Next) or `VITE_OPENCLAW_BASE_PATH=/openclaw/` (Vite).
- Optionally `NEXT_PUBLIC_OPENCLAW_WS_URL` / `VITE_OPENCLAW_WS_URL` to override WS URL (default is same-origin `/openclaw/ws`).

For local dev: set `NEXT_PUBLIC_OPENCLAW_WS_URL=ws://localhost:8081/ws` (or your backend WS path) if the backend serves WS on a different port.

## 4. Backend WS path

If your backend does **not** serve WebSocket at `/openclaw/ws`, change `WS_PATH` in `getOpenClawWsUrl.ts` to match (e.g. `/openclaw/socket` or `/ws` if Nginx rewrites). Nginx proxies the whole `/openclaw/` prefix to the app, so the backend can serve WS at `/ws` and the frontend can use `/openclaw/ws` (Nginx forwards it).
