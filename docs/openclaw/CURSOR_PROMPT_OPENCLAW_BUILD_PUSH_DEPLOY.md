# Prompt: build, push y imagen lista para deploy en LAB

**Pegar en Cursor con el repo ccruz0/openclaw abierto** (File → Open Folder → ~/openclaw).

Está pensado para que Cursor revise WebSocket, base path, .env.example, Dockerfile y devuelva los comandos de build/push y el checklist de verificación.

---

## Prompt (copiar y pegar tal cual)

```
You are working inside the repository ccruz0/openclaw.

Goal: produce and publish a working Docker image for the OpenClaw frontend so it runs correctly behind
https://dashboard.hilovivo.com/openclaw.

Current context:
- Framework: Vite.
- WebSocket must NOT use ws://localhost:8081.
- WebSocket must resolve to same-origin: /openclaw/ws.
- Base path must work under /openclaw/.
- Image must be published to ghcr.io/ccruz0/openclaw:latest.

Tasks:
1. Verify WebSocket implementation
Search the repository for:
- ws://localhost
- localhost:8081
- new WebSocket(
- "8081"

Ensure all WebSocket creation uses a helper called getOpenClawWsUrl().

The helper must behave like this:
- If env exists: VITE_OPENCLAW_WS_URL → use it.
- Otherwise derive from browser location:

const proto = window.location.protocol === "https:" ? "wss" : "ws";
const host = window.location.host;
return `${proto}://${host}/openclaw/ws`;

2. Confirm base path
Verify the Vite config supports /openclaw/.

If missing, add:

export default defineConfig({
  base: "/openclaw/",
})

Ensure assets load correctly when the app is served under /openclaw.

3. Verify .env.example
Ensure it contains:

VITE_OPENCLAW_WS_URL=wss://dashboard.hilovivo.com/openclaw/ws

4. Validate Dockerfile
Ensure Dockerfile builds the actual UI (not a placeholder) and serves the built files.

Expected flow:
npm install
npm run build
serve dist

5. Produce build instructions
Return the exact commands required to build and publish the image:

docker build -t ghcr.io/ccruz0/openclaw:latest .
docker push ghcr.io/ccruz0/openclaw:latest

6. Verification checklist
Provide a short checklist confirming that after deployment:
- /openclaw loads the real UI.
- Browser console does NOT show ws://localhost.
- Network tab shows WebSocket connection to /openclaw/ws.
- WebSocket returns status 101.

Deliverable:
- List of modified files.
- Key code snippets changed.
- Docker build + push commands.
- Short verification checklist.
```

---

## Después de aplicar

1. **Build + push (con Docker en marcha):**
   ```bash
   cd ~/openclaw
   docker build -t ghcr.io/ccruz0/openclaw:latest .
   docker push ghcr.io/ccruz0/openclaw:latest
   ```

2. **Redeploy en LAB** (EC2 Instance Connect o el método que uses):
   ```bash
   docker pull ghcr.io/ccruz0/openclaw:latest
   docker stop openclaw || true
   docker rm openclaw || true
   docker run -d --restart unless-stopped -p 8081:8081 --name openclaw ghcr.io/ccruz0/openclaw:latest
   docker logs --tail=120 openclaw
   ```

3. **Verificación:** https://dashboard.hilovivo.com/openclaw/ → sin placeholder, sin ws://localhost, WS a .../openclaw/ws con 101.

---

## Workflow de GitHub Actions (opcional)

**→ [CURSOR_PROMPT_OPENCLAW_GHCR_WORKFLOW.md](CURSOR_PROMPT_OPENCLAW_GHCR_WORKFLOW.md)** — Segundo prompt: pegar en ccruz0/openclaw para que Cursor cree `.github/workflows/docker_publish.yml`. Build y push automático a GHCR en push a main o `workflow_dispatch`; no hace falta Docker local.
