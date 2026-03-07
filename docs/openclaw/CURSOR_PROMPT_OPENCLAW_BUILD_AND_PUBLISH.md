# Prompt: Build and publish real OpenClaw image (use in repo ccruz0/openclaw)

**Use this when Cursor has the repo ccruz0/openclaw open (File → Open Folder → openclaw).**

Context (confirmed in browser):
- https://dashboard.hilovivo.com/openclaw/ shows: "Placeholder. Replace OPENCLAW_IMAGE with full app when ready."
- Console shows: WebSocket connection to 'ws://localhost:8081/' failed

Goal: Build and publish a real OpenClaw image to GHCR and make it work behind the dashboard proxy at UI path /openclaw/ and WebSocket path /openclaw/ws (same-origin, no localhost).

Constraints: Do NOT change automated-trading-platform. Do NOT change nginx. Fix only this repo and produce ghcr.io/ccruz0/openclaw:latest.

---

## Prompt (copy-paste into Cursor with ccruz0/openclaw open)

```
You are in the repository: ccruz0/openclaw.

Context (confirmed in browser):
- https://dashboard.hilovivo.com/openclaw/ shows: "Placeholder. Replace OPENCLAW_IMAGE with full app when ready."
- Console shows: WebSocket connection to 'ws://localhost:8081/' failed

Goal:
Build and publish a real OpenClaw image to GHCR and make it work behind the dashboard proxy at:
- UI path: /openclaw/
- WebSocket path: /openclaw/ws (same-origin, no localhost)

Constraints:
- Do NOT change automated-trading-platform repo.
- Do NOT change nginx.
- Fix only this repo and produce ghcr.io/ccruz0/openclaw:latest.

Tasks:

1) Verify this repo is the real frontend/app (not placeholder)
- Find any file/component that renders the placeholder text.
- Identify why it appears (default route? missing config? build flag?).
- Remove the placeholder behavior: default build must show the real app. If real app is missing, fail the build loudly (do not serve placeholder HTML).

2) Fix ALL hardcoded websocket URLs
- Search for: "ws://localhost", "localhost:8081", "8081", "new WebSocket("
- Create a single helper: getOpenClawWsUrl()
  - Prefer env: NEXT_PUBLIC_OPENCLAW_WS_URL, VITE_OPENCLAW_WS_URL
  - Fallback: protocol = https ? wss : ws, host = window.location.host, path = "/openclaw/ws", return `${protocol}://${host}${path}`
- Replace all WebSocket creation code to use getOpenClawWsUrl().

3) Make the app work under /openclaw base path
- Detect framework (Next.js vs Vite vs other).
- Configure: Next.js basePath "/openclaw", Vite base "/openclaw/"
- Ensure assets and refresh routing work under /openclaw.

4) Update .env.example
Add NEXT_PUBLIC_OPENCLAW_WS_URL=wss://dashboard.hilovivo.com/openclaw/ws and/or VITE_OPENCLAW_WS_URL=wss://dashboard.hilovivo.com/openclaw/ws

5) Docker build must produce the real app
- Confirm Dockerfile builds the correct frontend/app (not placeholder).
- Provide exact: docker build -t ghcr.io/ccruz0/openclaw:latest . && docker push ghcr.io/ccruz0/openclaw:latest

6) Deliverable
Return: Files changed, key diffs (helper + replacements + base path config), build/push commands, env vars, and verification checklist:
- Browser UI no longer shows placeholder
- Console has no ws://localhost:8081
- Network WS connects to wss://dashboard.hilovivo.com/openclaw/ws with 101
```

---

## After applying in ccruz0/openclaw

1. Build and push: `docker build -t ghcr.io/ccruz0/openclaw:latest .` then `docker push ghcr.io/ccruz0/openclaw:latest`
2. On LAB server: `docker pull ghcr.io/ccruz0/openclaw:latest` then restart the openclaw container with that image (see docs/openclaw/CURSOR_PROMPT_OPENCLAW_REAL_BUILD.md for exact commands).
3. Open https://dashboard.hilovivo.com/openclaw/ and verify: real UI, no placeholder, WebSocket to wss://dashboard.hilovivo.com/openclaw/ws (101).
