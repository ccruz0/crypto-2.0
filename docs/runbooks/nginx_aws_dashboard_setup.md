# Nginx + Docker stack AWS — dashboard.hilovivo.com

Configuración para que nginx sirva la plataforma (frontend + backend) del profile `aws` en lugar de la página por defecto.

---

## Conectarse a la instancia (Security Group real + SSH)

Sin inventar nada: sacar el SG de la instancia, abrir 22 para tu IP, conectar.

**1. Sacar el SG y la IP pública de la instancia:**

```bash
aws ec2 describe-instances \
  --instance-ids i-087953603011543c5 \
  --query 'Reservations[0].Instances[0].{State:State.Name,PublicIp:PublicIpAddress,SG:SecurityGroups[*].GroupId}' \
  --output table
```

**2. Con el `sg-...` que salga, abrir el 22 para tu IP:**

```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-XXXXXXXXXXXX \
  --protocol tcp \
  --port 22 \
  --cidr 185.214.97.189/32
```

(Sustituye `sg-XXXXXXXXXXXX` por el GroupId del paso 1; sustituye `185.214.97.189/32` por tu IP actual si es distinta.)

Si el paso 2 devuelve **InvalidPermission.Duplicate**, la regla ya existía; entonces el problema es otro (NACL, ruta, o que la instancia no tiene IP pública).

**3. Conectarse usando la IP pública del paso 1:**

```bash
ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@PUBLIC_IP
```

(`PUBLIC_IP` = valor `PublicIp` del paso 1.)

---

## 0) Inbound vs Outbound (por qué “quitar” y “poner” no es contradictorio)

- **Quitar** reglas/puertos era para no abrir cosas innecesarias en internet (inbound amplio, puertos expuestos).
- **Poner** salida (outbound) era para que la instancia pueda llegar a apt/Ubuntu, Docker Hub, etc. Sin outbound no se puede instalar ni actualizar nada.

**Mínimo correcto:**

| Dirección | Regla |
|-----------|--------|
| **Inbound** | Solo lo que uses: SSH desde tu IP, 80/443 si sirves web. |
| **Outbound** | Permitir salida: idealmente “All traffic 0.0.0./0” o, si quieres fino, al menos 80/443 + DNS. |

Si apt/update fallaba por red, el bloqueo era **outbound**; al abrirlo vuelve a funcionar apt.

---

## 1) Plan de ejecución en la instancia

### Dónde está el proyecto en la instancia

En la instancia el repo puede estar en `~/crypto-2.0` (si clonaste `https://github.com/ccruz0/crypto-2.0.git`) o en `~/automated-trading-platform`. La regla es:

**Ejecuta `docker compose` desde la carpeta que contiene el `docker-compose.yml` correcto.**

Para comprobarlo en la instancia:

```bash
cd ~
ls -la
find . -maxdepth 2 -name "docker-compose.yml"
```

El `find` te dice exactamente en qué ruta está el compose real (p. ej. `./crypto-2.0/docker-compose.yml` → usa `cd ~/crypto-2.0`). Pega ese resultado si quieres cerrar la duda. Luego en todos los comandos sustituye `~/crypto-2.0` por esa carpeta si es distinta.

### Comandos de diagnóstico

Ejecuta en la instancia y pega la salida **completa** para diagnosticar. Si algo falla en un paso, pega también el error tal cual. (Ajusta el `cd` si el proyecto está en otra carpeta.)

```bash
cd ~/crypto-2.0
docker compose --profile aws config --services
docker compose --profile aws up -d --build
docker compose --profile aws ps
ss -tlnp | grep -E '3000|8002' || true
curl -sS -I http://127.0.0.1:3000 | head
curl -sS -I http://127.0.0.1:8002/health || true
```

**Nota:** El endpoint `/health` puede no existir en tu backend. Si ese `curl` falla (404/timeout), **no** significa que el backend esté caído; solo que ese path no existe. En ese caso ejecuta este bloque extra para comprobar que el backend responde:

```bash
curl -sS -I http://127.0.0.1:8002/ | head
curl -sS -I http://127.0.0.1:8002/docs | head || true
curl -sS http://127.0.0.1:8002/openapi.json | head -c 200 || true
```

Para confirmar que nginx está usando **tu** site (y no el default), ejecuta también:

```bash
sudo nginx -T 2>/dev/null | sed -n '1,120p' | head
sudo nginx -T 2>/dev/null | grep -n "server_name dashboard.hilovivo.com" -B2 -A40
ls -la /etc/nginx/sites-enabled
```

*(`nginx -T` saca mucho por stderr; el `2>/dev/null` evita que el grep se ensucie.)*

**Qué debe verse:**

- `frontend-aws` y `backend-aws` en estado **Up**
- Listeners en **127.0.0.1:3000** y **127.0.0.1:8002**
- `curl` al frontend (3000): algo razonable (200/302)
- `curl` al backend: 200 en algún path (`/health`, `/`, `/docs` o `openapi.json` según lo que exponga el backend)

**Importante:** Si `docker compose --profile aws ps` muestra frontend-aws y backend-aws en **Up**, y `ss -tlnp` muestra **127.0.0.1:3000** y **127.0.0.1:8002**, entonces el **90% del problema** es nginx apuntando al site equivocado o un `location` mal configurado. Los comandos de nginx de arriba sirven para verificarlo.

Con la salida completa se puede ver qué servicio falla, si el backend necesita base path `/api`, y si nginx está usando el site correcto.

---

## 2) Nginx: aplicar el bloque y comprobar

### 2.1 Dónde está el server actual

En la instancia (el path que salga es el que debes editar). `nginx -T` escribe mucho por stderr; `2>/dev/null` evita que el grep se ensucie.

```bash
sudo nginx -T 2>/dev/null | grep -n -B2 -A30 "server_name dashboard.hilovivo.com"
```

La salida indica en qué archivo está el `server` (p. ej. `configuration file /etc/nginx/sites-available/dashboard.hilovivo.com`).

### 2.2 Editar ese archivo

No adivines rutas; usa el archivo que mostró el comando anterior. Ejemplo:

```bash
sudo nano /etc/nginx/sites-available/dashboard.hilovivo.com
```

Pega el bloque de configuración que está más abajo (sección “Configuración exacta de nginx”).

### 2.3 Activar y recargar

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 2.4 Probar desde la instancia

```bash
curl -sS -I http://127.0.0.1/ | head
curl -sS -I http://127.0.0.1/api/ | head
```

Y desde tu Mac:

```bash
curl -sS -I https://dashboard.hilovivo.com | head
```

---

## Puertos del stack (docker-compose.yml)

| Servicio        | Puerto en host     | Uso                 |
|-----------------|--------------------|---------------------|
| **frontend-aws** | `127.0.0.1:3000`  | Dashboard (Next.js) |
| **backend-aws**  | `127.0.0.1:8002`  | API                 |
| grafana         | 127.0.0.1:3001    | Observabilidad      |

Nginx debe hacer proxy a **3000** (frontend) y **8002** (backend). No asumir puertos: confirmar con `ss -tlnp | grep -E '3000|8002'`.

---

## Configuración exacta de nginx

Incluye headers necesarios, soporte websocket y timeout seguro. Sustituye el `server` que tenga `server_name dashboard.hilovivo.com` (y cualquier `root /var/www/html`) por esto:

```nginx
server {
    listen 80;
    server_name dashboard.hilovivo.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8002;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 60s;
        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;
    }
}
```

---

## 3) Prompt para Cursor (inglés)

Para que Cursor ejecute de forma metódica (sin inventar puertos, cambios mínimos), copia esto en Cursor:

```
You are working on repo "crypto-2.0" (Automated Trading Platform) deployed on an AWS EC2 Ubuntu 24.04 instance behind nginx at https://dashboard.hilovivo.com.

Goal:
Make the platform fully operational in production:
- Frontend served at / (dashboard.hilovivo.com)
- Backend served at /api/
- Docker Compose stack runs reliably using profile "aws"
- nginx reverse proxy routes correctly to local loopback ports
- Provide a verification checklist and small scripts/runbooks to reproduce and debug

Hard constraints:
- Do NOT expose backend/db ports publicly. Bind to 127.0.0.1 only.
- Do NOT broaden inbound security group rules; keep inbound minimal.
- Outbound must allow apt/docker pulls (80/443 + DNS or all outbound).
- Prefer minimal diffs; do not rewrite the whole repo.
- Never assume ports: read docker-compose.yml and confirm via `ss -tlnp`.
- Always include `cd` before commands when referencing a directory.

What to do:
1) Inspect docker-compose.yml:
   - Identify AWS profile services, especially frontend-aws and backend-aws
   - Confirm which host ports they bind to (expected: 127.0.0.1:3000 for frontend, 127.0.0.1:8002 for backend)
   - Confirm any health endpoints and base paths

2) Create/Update an nginx site config for dashboard.hilovivo.com:
   - Route "/" -> http://127.0.0.1:<frontend_port>
   - Route "/api/" -> http://127.0.0.1:<backend_port>
   - Include required proxy headers
   - Include Upgrade/Connection headers for websocket support
   - Add a safe default timeout (e.g. proxy_read_timeout 60s)

3) Add a production verification runbook:
   - Commands to run on EC2 to bring stack up: `docker compose --profile aws up -d --build`
   - Commands to confirm services are up: `docker compose --profile aws ps`
   - Commands to confirm listeners: `ss -tlnp | grep -E '<ports>'`
   - Commands to test locally: `curl -I http://127.0.0.1:<port>`
   - Commands to test public domain
   - Commands to view logs for specific services

4) Add a troubleshooting section:
   - If docker shows "no service selected" explain how to use profile flags
   - If nginx shows default page, explain how to find which site is active (`nginx -T`)
   - If backend works locally but not via domain, explain path prefix and nginx location ordering
   - If apt has connectivity issues, diagnose SG outbound vs route table vs NAT

Deliverables:
- Exact file(s) to change in repo (if any) and the diffs
- Exact nginx config content
- A concise runbook markdown file under docs/runbooks/ (create if missing)
- A final "Definition of Done" checklist with objective tests

Start by reading docker-compose.yml and determining real ports and service names. Then propose minimal changes and verification commands.
```

(La regla equivalente está en `.cursor/rules/ec2-nginx-production.mdc` para que Cursor la aplique en archivos de compose, nginx y runbooks.)

---

## 4) Base de datos y secrets en EC2

Para que el backend deje de devolver errores por tablas inexistentes y Telegram/Exchange funcionen, hay que: (1) asegurar que el esquema de la BD exista, (2) configurar secrets en la instancia.

### 4.1 Inicialización del esquema (tablas)

El backend crea todas las tablas al arrancar (`Base.metadata.create_all`) si están registrados los modelos. Tras un **pull** del repo que incluye el fix (import de `app.models` antes de `create_all` y modelos de portfolio en `app.models`):

1. En la instancia, desde el directorio del proyecto (p. ej. `~/crypto-2.0`):
   ```bash
   cd ~/crypto-2.0
   git pull
   docker compose --profile aws up -d --build backend-aws
   ```
2. Revisar logs: deberían aparecer "Database tables initialized" y ya no "relation ... does not exist".
3. **No ejecutar** en AWS la migración `backend/migrations/20260128_create_watchlist_signal_states.sql`: en producción se usa la tabla en singular `watchlist_signal_state`. (Véase README-ops.md / DEPLOY_MAIN_TO_AWS_RUNBOOK.md.)

Otras migraciones en `backend/migrations/` (por ejemplo columnas opcionales, índices) pueden aplicarse si hace falta, ejecutando el SQL contra la BD del stack, por ejemplo:

```bash
docker compose --profile aws exec -T db psql -U trader -d atp < backend/migrations/add_dashboard_indexes.sql
```

Solo aplicar migraciones que no entren en conflicto con el esquema actual.

### 4.2 Secrets y variables de entorno (AWS)

El profile `aws` carga, por orden: `.env`, `.env.aws`, `secrets/runtime.env`. **No** se carga `.env.local` para `backend-aws` (evita mezclar credenciales locales).

1. **`.env.local`**  
   Puede quedar vacío en EC2; solo hace falta que exista si `docker-compose` referencia `env_file: .env.local` y falla al no encontrarlo (en ese caso `touch .env.local` es suficiente).

2. **`.env.aws`** (obligatorio para producción)  
   - Copiar la plantilla: `ops/atp.env.template` → en la instancia crear/editar `.env.aws`.
   - Rellenar al menos:
     - `POSTGRES_PASSWORD`, `DATABASE_URL` (misma contraseña que usa el servicio `db`).
     - `SECRET_KEY` (generar con `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`).
     - `TELEGRAM_BOT_TOKEN_ENCRYPTED`, `TELEGRAM_CHAT_ID_AWS` (o `TELEGRAM_CHAT_ID`) si usas Telegram.
     - `EXCHANGE_CUSTOM_API_KEY`, `EXCHANGE_CUSTOM_API_SECRET` para Crypto.com (y `AWS_INSTANCE_IP` = IP elástica de la instancia para whitelist).
     - `ENVIRONMENT=aws`, `APP_ENV=aws`, `RUNTIME_ORIGIN=AWS`, `RUN_TELEGRAM=true`.
     - `FRONTEND_URL` / `API_BASE_URL` según tu dominio (p. ej. `https://dashboard.hilovivo.com`).

3. **`secrets/runtime.env`** (recomendado para secrets sensibles)  
   - En el repo: `secrets/runtime.env.example` lista las variables (sin valores).
   - En la instancia: crear `secrets/runtime.env` con los valores reales (no commitear). Típicamente: `TELEGRAM_BOT_TOKEN_ENCRYPTED`, `TELEGRAM_CHAT_ID`, `ADMIN_ACTIONS_KEY`, `DIAGNOSTICS_API_KEY`. Si usas token de Telegram cifrado, el archivo de clave (p. ej. `secrets/telegram_key` o el path que use `TELEGRAM_KEY_FILE`) debe estar en la instancia con los mismos permisos que en el runbook de Telegram.

4. **Reiniciar el stack** tras cambiar env:
   ```bash
   cd ~/crypto-2.0
   docker compose --profile aws up -d backend-aws market-updater-aws
   ```
   Revisar logs de `backend-aws` para confirmar que no hay 401/404 por token o API keys.

Resumen: con esquema creado (reinicio de backend tras el fix) y `.env.aws` + `secrets/runtime.env` rellenados, el dashboard y la API deberían funcionar sin errores de tablas ni de credenciales faltantes.

---

## Verificación en producción

Ejecutar **en la instancia** (después de `docker compose --profile aws up -d --build`):

| Comprobación | Comando |
|--------------|---------|
| Servicios del profile aws | `cd ~/crypto-2.0 && docker compose --profile aws config --services` |
| Estado de contenedores | `cd ~/crypto-2.0 && docker compose --profile aws ps` |
| Listeners frontend/backend | `ss -tlnp \| grep -E '3000\|8002'` |
| Frontend local | `curl -sS -I http://127.0.0.1:3000 \| head` |
| Backend health local | `curl -sS -I http://127.0.0.1:8002/health \| head` o `/api/health` |
| Nginx raíz (local) | `curl -sS -I http://127.0.0.1/ \| head` |
| Nginx API (local) | `curl -sS -I http://127.0.0.1/api/ \| head` |

Desde tu Mac:

| Comprobación | Comando |
|--------------|---------|
| Dominio público | `curl -sS -I https://dashboard.hilovivo.com \| head` |

Logs de un servicio concreto:

```bash
cd ~/crypto-2.0
docker compose --profile aws logs -f backend-aws
docker compose --profile aws logs -f frontend-aws
```

---

## Troubleshooting

### Docker: “no service selected” o no levanta nada

- Usa siempre el profile: `docker compose --profile aws up -d --build`.
- Lista servicios: `docker compose --profile aws config --services`.

### Nginx muestra “Welcome to nginx”

- El default suele ganar por nombre o por orden. Encuentra qué site está activo:
  - `sudo nginx -T 2>/dev/null | grep -n -B2 -A30 "server_name dashboard.hilovivo.com"`
  - Revisa `sites-enabled`: el que tenga `default` o escuchar `80` sin `server_name` puede estar capturando todo. Asegura que el site de `dashboard.hilovivo.com` esté en `sites-enabled` y que el server tenga `server_name dashboard.hilovivo.com` y los `location` de proxy (no `root /var/www/html`).

### Backend responde local pero no por el dominio

- Comprueba que nginx tenga `location /api/` con `proxy_pass http://127.0.0.1:8002` (trailing slash según cómo quieras reescribir la URI).
- El backend ya monta rutas bajo `/api` (p. ej. `/api/health`). Con `location /api/` y `proxy_pass http://127.0.0.1:8002` la petición llega como `/api/...` al backend, que es correcto.
- Orden de `location`: más específico primero (`/api/` antes que `/`).

### Apt / conectividad desde la instancia

- Si `apt update` o descargas fallan, suele ser **outbound** (security group o tabla de rutas).
- Revisa reglas de salida del SG: permitir al menos 80/443 (y DNS si usas resolvers externos) o “All traffic” a 0.0.0.0/0.
- Si la instancia está en subnet privada, comprueba NAT Gateway / rutas para que el tráfico de salida llegue a internet.

---

## Definition of Done (checklist objetivo)

- [ ] En la instancia: `docker compose --profile aws ps` muestra `frontend-aws` y `backend-aws` **Up**.
- [ ] `ss -tlnp` muestra listeners en **127.0.0.1:3000** y **127.0.0.1:8002**.
- [ ] En la instancia: `curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:3000` devuelve 200 o 302.
- [ ] En la instancia: algún endpoint del backend responde 200 (p. ej. `curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/health` o `.../` o `.../docs`; si `/health` no existe, no es fallo del backend).
- [ ] En la instancia: `curl -sS -I http://127.0.0.1/` no es “Welcome to nginx”; es respuesta del frontend o redirect.
- [ ] En la instancia: `curl -sS -I http://127.0.0.1/api/` devuelve respuesta del backend (p. ej. 200 o 404 de FastAPI).
- [ ] Desde Mac: `curl -sS -I https://dashboard.hilovivo.com` devuelve 200/301/302 y no página por defecto de nginx.

Cuando todo lo anterior se cumple, el dashboard está operativo en producción vía nginx + stack AWS.
