# Prompt para pegar en Cursor (repo ccruz0/openclaw)

Abre **ccruz0/openclaw** en Cursor (File → Open Folder) y pega el bloque siguiente en el chat.

---

## Prompt (copy-paste)

```
You are working inside the repository ccruz0/openclaw.

Goal:
Make OpenClaw work correctly behind https://dashboard.hilovivo.com/openclaw/.

The current deployment shows a placeholder UI and the browser console reports a WebSocket error like:

WebSocket connection to 'ws://localhost:8081/' failed

This means the frontend is incorrectly hardcoding a localhost WebSocket instead of using the same origin.

Follow these steps carefully.

Step 1 — Detect framework
Check package.json and project structure to determine whether this is:
• Next.js
• Vite
• another React-based frontend

Report which framework is used before applying changes.

Step 2 — Find WebSocket usage
Search the repository for any of these patterns:

ws://localhost
localhost:8081
new WebSocket(
"/ws"

List the exact files and lines where WebSocket URLs are defined.

Step 3 — Implement a WebSocket URL helper
Create a helper that builds the correct URL.

Example logic:
• If an env variable exists: NEXT_PUBLIC_OPENCLAW_WS_URL or VITE_OPENCLAW_WS_URL — use it.
• Otherwise derive from the browser location:
  protocol = window.location.protocol === "https:" ? "wss" : "ws"
  host = window.location.host
  path = "/openclaw/ws"
  Return: protocol + "://" + host + path

Name the helper something like getOpenClawWsUrl(). Place it in a logical location such as:
src/lib/getOpenClawWsUrl.ts or src/utils/getOpenClawWsUrl.ts

Step 4 — Replace all hardcoded WebSocket URLs
Replace every occurrence of ws://localhost:8081 with getOpenClawWsUrl(). All WebSocket connections must go through this helper.

Step 5 — Ensure the app works under /openclaw base path
If the project is Next.js: add in next.config.js: basePath: "/openclaw"
If the project is Vite: set in vite.config.ts: base: "/openclaw/"
Ensure assets, routing and refresh work correctly under this path.

Step 6 — Environment example
Create or update .env.example with:
NEXT_PUBLIC_OPENCLAW_WS_URL=wss://dashboard.hilovivo.com/openclaw/ws
or
VITE_OPENCLAW_WS_URL=wss://dashboard.hilovivo.com/openclaw/ws

Step 7 — Docker image
Verify the Dockerfile builds the frontend correctly. Provide the commands needed to build and push:
docker build -t ghcr.io/ccruz0/openclaw:latest .
docker push ghcr.io/ccruz0/openclaw:latest

Step 8 — Verification checklist
After deployment the following must be true:
• Browser URL: https://dashboard.hilovivo.com/openclaw/
• Console: No "ws://localhost:8081" errors
• Network tab: WebSocket connects to wss://dashboard.hilovivo.com/openclaw/ws — Status: 101 Switching Protocols

Step 9 — Output
Return:
1. List of files modified
2. Exact code changes
3. Build and push commands
4. Any new environment variables required
5. Short verification checklist
```

---

## Variante más agresiva (opcional)

Si quieres un prompt que pida a Cursor que **encuentre automáticamente todos los sitios donde se usa WebSocket y los parchee en una sola pasada**, pídelo y se puede añadir aquí como segunda variante.
