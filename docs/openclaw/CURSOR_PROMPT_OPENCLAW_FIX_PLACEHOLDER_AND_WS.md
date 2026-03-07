# Prompt para Cursor (repo ccruz0/openclaw) — Fix placeholder + WebSocket

**Origen del placeholder en producción:** La imagen que muestra "Placeholder. Replace OPENCLAW_IMAGE..." viene del **Dockerfile en ATP** (`openclaw/Dockerfile`), que sirve un HTML estático. En LAB hay que usar una imagen construida desde **ccruz0/openclaw** (frontend real) para que desaparezca el placeholder y funcione el WebSocket.

Abre el repo **ccruz0/openclaw** en Cursor y pega el bloque siguiente.

---

## Prompt (copy-paste)

```
You are in the repository ccruz0/openclaw.

Current problem (confirmed in browser):
- The page shows: "Placeholder. Replace OPENCLAW_IMAGE with full app when ready."
- Console shows: WebSocket connection to 'ws://localhost:8081/' failed

Goal:
When served behind https://dashboard.hilovivo.com/openclaw/ the UI must be the real app (not placeholder) and WebSocket must connect to same-origin:
wss://dashboard.hilovivo.com/openclaw/ws

Do NOT touch the automated-trading-platform repo.
Do NOT change nginx on the dashboard host.
Fix only this repo and make it buildable as ghcr.io/ccruz0/openclaw:latest.

Steps:

1) Identify what is serving the placeholder
- Find where the "Placeholder. Replace OPENCLAW_IMAGE..." text lives.
- Explain which file/component produces it and under what condition it shows.

2) Remove placeholder behavior
- Make the default build show the real app UI.
- If the real app is missing, fail the build with a clear error instead of serving the placeholder.

3) Fix WebSocket URL everywhere
- Search for any hardcoded: ws://localhost, localhost:8081, 8081, new WebSocket(
- Replace ALL websocket URL construction with a single helper function:
  - Name: getOpenClawWsUrl()
  - Location: src/lib/getOpenClawWsUrl.ts (or closest existing utils folder)
  - Logic:
      If NEXT_PUBLIC_OPENCLAW_WS_URL exists, use it.
      Else if VITE_OPENCLAW_WS_URL exists, use it.
      Else derive from window.location:
        protocol = (window.location.protocol === "https:") ? "wss" : "ws"
        host = window.location.host
        path = "/openclaw/ws"
        return `${protocol}://${host}${path}`

4) Ensure base path works under /openclaw
- If Next.js: set basePath = "/openclaw" and ensure assets work.
- If Vite: set base = "/openclaw/" and ensure routing works on refresh.
- Make sure any internal links, fetches, and asset paths are compatible with /openclaw.

5) Environment example
- Update .env.example with:
  NEXT_PUBLIC_OPENCLAW_WS_URL=wss://dashboard.hilovivo.com/openclaw/ws
  (and/or) VITE_OPENCLAW_WS_URL=wss://dashboard.hilovivo.com/openclaw/ws

6) Docker
- Verify the Dockerfile builds the correct frontend (no placeholder).
- Provide exact build/push commands:
  docker build -t ghcr.io/ccruz0/openclaw:latest .
  docker push ghcr.io/ccruz0/openclaw:latest

7) Deliverable
Return:
- List of files changed
- Key diffs (the exact new helper code + where it is used)
- Any config changes for base path
- Build/push commands
- Quick verification steps:
  - Open https://dashboard.hilovivo.com/openclaw/
  - DevTools Console has no ws://localhost:8081
  - Network WS shows wss://dashboard.hilovivo.com/openclaw/ws with 101
```

---

## Nota sobre el placeholder

El mensaje "Placeholder. Replace OPENCLAW_IMAGE with full app when ready." que ves en **dashboard.hilovivo.com/openclaw/** puede venir de:

1. **Imagen construida desde ATP** (`openclaw/Dockerfile` en automated-trading-platform): ese Dockerfile genera ese HTML. En LAB, si usas esa imagen, verás el placeholder.
2. **Imagen construida desde ccruz0/openclaw**: si el repo openclaw tiene su propia UI (aunque sea mínima) y un Dockerfile que la sirve, al hacer build/push desde ccruz0/openclaw y desplegar **esa** imagen en LAB, el placeholder desaparece y ves la app real (y el fix del WebSocket aplica).

Por tanto: el “fix” del placeholder en producción es **usar la imagen de ccruz0/openclaw** en LAB, no la de ATP. Este prompt hace que el repo ccruz0/openclaw esté listo (UI real + WebSocket same-origin + base path) y construya `ghcr.io/ccruz0/openclaw:latest`.
