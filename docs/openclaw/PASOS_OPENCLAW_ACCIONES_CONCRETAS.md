# OpenClaw: acciones concretas (sin vueltas)

## Paso 1: Abrir el repo correcto en Cursor

**En terminal:**

```bash
cd ~
git clone https://github.com/ccruz0/openclaw.git
```

**En Cursor:**

- **File → Open Folder**
- Elige `~/openclaw`

Si ya lo tienes clonado en otro sitio, abre ese folder.

---

## Paso 2: Pegar este prompt en Cursor (con el repo ccruz0/openclaw abierto)

Copia y pega tal cual:

```
You are in repo: ccruz0/openclaw.

We have a confirmed production symptom:
- https://dashboard.hilovivo.com/openclaw/ shows a placeholder page.
- Console shows: WebSocket connection to 'ws://localhost:8081/' failed.

Target behavior:
- UI works behind /openclaw/
- WebSocket connects to same-origin: wss://dashboard.hilovivo.com/openclaw/ws
- No hardcoded ws://localhost:8081 anywhere.
- Build/push image: ghcr.io/ccruz0/openclaw:latest

Constraints:
- Do not edit automated-trading-platform.
- Do not edit nginx.

Do this:

1) Identify framework and entrypoints
- Determine if this is Next.js, Vite, or something else (package.json + config files).
- Identify the real app entry component(s).

2) Remove placeholder behavior
- Find the exact source of the placeholder content.
- Make the default build show the real UI.
- If a required config is missing, fail build with a clear error instead of serving placeholder HTML.

3) WebSocket fix (global)
- Search for all occurrences:
  "ws://localhost", "localhost:8081", "8081", "new WebSocket("
- Create helper getOpenClawWsUrl():
  - Prefer env:
    NEXT_PUBLIC_OPENCLAW_WS_URL
    VITE_OPENCLAW_WS_URL
  - Else derive from window.location:
    proto = (https:) ? wss : ws
    host = window.location.host
    return `${proto}://${host}/openclaw/ws`
- Replace ALL websocket constructions to use this helper.

4) Base path /openclaw
- Ensure the app works when hosted under /openclaw:
  - Next.js: basePath "/openclaw"
  - Vite: base "/openclaw/"
- Ensure assets + router refresh works.

5) .env.example
Add:
- NEXT_PUBLIC_OPENCLAW_WS_URL=wss://dashboard.hilovivo.com/openclaw/ws
and/or
- VITE_OPENCLAW_WS_URL=wss://dashboard.hilovivo.com/openclaw/ws

6) Docker
- Ensure Dockerfile builds the real app.
- Provide exact commands:
  docker build -t ghcr.io/ccruz0/openclaw:latest .
  docker push ghcr.io/ccruz0/openclaw:latest

Deliverable:
- List of files changed
- Key diffs (helper + where it is used + base path config)
- Build/push commands
- Quick verification checklist for the browser (no placeholder, no localhost WS, WS 101)
```

---

## Paso 3: En paralelo (mientras Cursor trabaja) — redeploy en LAB

No requiere SSM. Si tienes acceso por EC2 Instance Connect al LAB:

```bash
docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw || true
docker rm openclaw || true
docker run -d --restart unless-stopped -p 8081:8081 --name openclaw ghcr.io/ccruz0/openclaw:latest
docker logs --tail=80 openclaw
```

Luego abre de nuevo: **https://dashboard.hilovivo.com/openclaw/**

**Confirma:**

- Ya no sale el placeholder
- En consola no aparece `ws://localhost:8081`
- En Network → WS ves `.../openclaw/ws` con 101

---

## Si Cursor responde “no encuentro placeholder” o “no sé qué framework es”

Pégame aquí solo:

- `package.json` (scripts + deps relevantes)
- Lista de archivos en raíz (`ls`)
- Dónde encontró `new WebSocket(`

y te digo exactamente qué archivo tocar.
