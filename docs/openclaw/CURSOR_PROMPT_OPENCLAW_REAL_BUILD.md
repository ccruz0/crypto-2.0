# Prompt para Cursor (en el repo ccruz0/openclaw)

**Contexto:** El diagnóstico en ATP ya mostró que `/openclaw` responde, nginx proxy y upstream funcionan, pero la app es el **placeholder** y el WebSocket apunta a `localhost:8081`. El siguiente paso **no es tocar ATP ni nginx**; es arreglar el repo **ccruz0/openclaw** y desplegar la imagen real.

---

## Siguiente paso exacto

### 1. Abrir el repo correcto

En Cursor: **File → Open Folder** → abre **ccruz0/openclaw**.  
No abras `automated-trading-platform`.

### 2. Ejecutar el prompt

Copia el **Prompt (copy-paste)** de más abajo y pégalo en el chat de Cursor con el repo **openclaw** abierto. Ese prompt hará que Cursor:

1. Busque `ws://localhost:8081`
2. Cree helper WebSocket same-origin
3. Use `wss://dashboard.hilovivo.com/openclaw/ws`
4. Añada base path `/openclaw`
5. Construya la imagen real
6. Publique `ghcr.io/ccruz0/openclaw`

### 3. Después: desplegar en LAB

Cuando Cursor termine (build + push), en el **servidor LAB** ejecuta:

```bash
docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw
docker rm openclaw
docker run -d -p 8081:8081 --name openclaw ghcr.io/ccruz0/openclaw:latest
```

(Si OpenClaw corre con docker-compose o systemd, usa el mismo flujo: pull nueva imagen y reiniciar el servicio/contenedor con esa imagen.)

### 4. Resultado esperado

Abrir **https://dashboard.hilovivo.com/openclaw/**:

| Antes | Después |
|-------|---------|
| "Placeholder. Replace OPENCLAW_IMAGE..." | UI completa de OpenClaw |
| Chat no responde | Chat funcionando |
| Consola: `WebSocket connection to ws://localhost:8081 failed` | Sin ese error |

### 5. Señal rápida en consola del navegador

- **Antes:** `WebSocket connection to ws://localhost:8081 failed`
- **Después:** conexión a `wss://dashboard.hilovivo.com/openclaw/ws` (en pestaña Network o en los logs de la app)

---

## Prompt (copy-paste)

```
You are in the repository ccruz0/openclaw.

Goal: build and deploy the real OpenClaw application image that replaces the placeholder currently shown at
https://dashboard.hilovivo.com/openclaw/

Current evidence from production:
• The page shows: "Placeholder. Replace OPENCLAW_IMAGE with full app when ready."
• Browser console error: WebSocket connection to ws://localhost:8081 failed.
• Therefore the deployed image is only a placeholder build.

Tasks:
1. Locate the frontend application entrypoint.
   Search for: package.json, src/, vite.config, next.config, dockerfile

2. Confirm the real UI exists in the repo (React/Vite/Next).

3. Search for hardcoded websocket endpoints:
   grep -R "ws://localhost" -n .
   grep -R "8081" -n .
   grep -R "WebSocket(" -n .

4. Implement a WebSocket URL helper so the app works behind:
   https://dashboard.hilovivo.com/openclaw/

   Rules:
   - If env variable exists: OPENCLAW_WS_URL — use it.
   - Otherwise compute same-origin:
     protocol: https -> wss, http -> ws
     host: window.location.host
     path: /openclaw/ws
   Example:
     const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
     const wsUrl = protocol + window.location.host + "/openclaw/ws";

5. Replace all direct usages of ws://localhost:8081 with this helper.

6. Ensure the app supports base path /openclaw/:
   Vite: base: "/openclaw/"
   Next.js: basePath: "/openclaw"

7. Update .env.example:
   OPENCLAW_WS_URL=/openclaw/ws

8. Build the production image. Expected: ghcr.io/ccruz0/openclaw

9. Provide: files modified, diff patch, docker build command, docker push command.

Deliverable: A working OpenClaw image that loads the real UI and connects to WebSocket at
wss://dashboard.hilovivo.com/openclaw/ws
```

---

## Qué pasará después

Cuando se despliegue la imagen real en LAB y el dashboard siga haciendo proxy a LAB:

- **https://dashboard.hilovivo.com/openclaw/** mostrará la UI completa de OpenClaw.
- El WebSocket funcionará en `wss://dashboard.hilovivo.com/openclaw/ws`.
- Desaparecerá el error en consola `WebSocket connection to ws://localhost:8081 failed`.

---

## Ver en ~30 s qué contenedor OpenClaw corre (LAB)

Desde el repo **automated-trading-platform** (con AWS CLI y SSM al LAB):

```bash
./scripts/openclaw/verify_openclaw_container_ssm.sh
```

Muestra imagen y nombre del contenedor en LAB. Si SSM no está Online, usa las opciones siguientes.

**Opción B — En el servidor LAB (SSH o Session Manager):**
```bash
docker ps --format "{{.Image}}\t{{.Names}}" | grep -i openclaw
# o
docker images | grep openclaw
```

- Si ves algo como `ghcr.io/ccruz0/crypto-2.0:openclaw` o un tag "placeholder" → es el placeholder.
- Si ves `ghcr.io/ccruz0/openclaw:latest` (o el tag que hayas pusheado) → es la imagen real del repo openclaw.

**Opción C — Desde el navegador:**  
Si la página muestra el texto literal "Placeholder. Replace OPENCLAW_IMAGE with full app when ready.", la instancia está sirviendo el placeholder. Tras desplegar la imagen real, esa frase desaparece y ves la UI real.
