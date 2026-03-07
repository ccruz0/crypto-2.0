# OpenClaw Web UI in Hilovivo Dashboard

OpenClaw’s native web UI is exposed at **https://dashboard.hilovivo.com/openclaw/** and embedded in the dashboard at **/openclaw** (iframe). No re-skin; the UI is proxied and framed as-is.

**Production vs local:** The domain **dashboard.hilovivo.com** is served by a **remote Ubuntu server** (Nginx there), not by your Mac. Anything you do with Nginx or htpasswd **on your Mac** (Homebrew, `/opt/homebrew/etc/nginx/`) does **not** affect production. To change production you must **SSH into the Ubuntu server** that serves the dashboard and edit/reload Nginx and create htpasswd **there** (paths like `/etc/nginx/`, `systemctl reload nginx`). Use the Mac/Homebrew notes only for local dev.

**Production:** Basic Auth is **on** by default. Create the htpasswd file on the **server** before (or immediately after) deploying the config; see §3.

---

## 0. Production hardening checklist (verify after deploy)

| Check | How |
|-------|-----|
| **1) No sensitive API exposed without auth** | From the dashboard server: `curl -I https://dashboard.hilovivo.com/openclaw/` and `curl -I https://dashboard.hilovivo.com/openclaw/api/`. If OpenClaw exposes endpoints like `/execute`, `/run`, `/internal`, `/admin`, they must be protected (Basic Auth is on for the whole `/openclaw/` path). |
| **2) LAB port 8080 not public** | Security Group of the LAB instance: **8080 must not be open to 0.0.0.0/0**. Only the dashboard server IP (or VPC/internal) should be allowed. If 8080 is open to the world, the proxy adds no security. Prefer: LAB in private subnet, dashboard as sole entry. |
| **3) CSP applied to /openclaw/** | In the browser: DevTools → Network → select a request to `/openclaw/` → Response headers. Must include `Content-Security-Policy: frame-ancestors 'self' https://dashboard.hilovivo.com`. No stricter global CSP overriding it. |

---

## 1. Enable / disable the route

- **Enable:** The Nginx location `^~ /openclaw/` is in `nginx/dashboard.conf`. Deploy the config and reload Nginx.
- **Disable:** Remove or comment out the whole `location ^~ /openclaw/ { ... }` block in `nginx/dashboard.conf`, then reload Nginx. The dashboard route `/openclaw` will still exist but the iframe will get 404.

---

## 2. Change LAB host / port

- **File:** `nginx/dashboard.conf`
- **Line:** Inside `location ^~ /openclaw/`, the line:
  ```nginx
  proxy_pass http://52.77.216.100:8080/;
  ```
- **Change:** Replace `52.77.216.100:8080` with your LAB host and port (e.g. `lab.example.com:8080`).
- **Apply:** Reload Nginx: `sudo nginx -t && sudo systemctl reload nginx`.

---

## 3. Basic auth (on by default)

- **Status:** Basic Auth is enabled in `nginx/dashboard.conf` for `/openclaw/`. The agent can create PRs; do not leave it without auth in production.
- **Before first reload:** Create the password file or Nginx will fail to start.

**Linux (production server):**
  ```bash
  sudo htpasswd -c /etc/nginx/.htpasswd_openclaw <username>
  ```
  Enter the password when prompted. For additional users: `sudo htpasswd /etc/nginx/.htpasswd_openclaw <other_user>` (no `-c`).
- **Rotate password:** Overwrite the user:
  ```bash
  sudo htpasswd /etc/nginx/.htpasswd_openclaw <username>
  ```
  Then reload: `sudo nginx -t && sudo systemctl reload nginx`

**macOS (Homebrew nginx):** `/etc/nginx/` often doesn't exist or isn't writable.

- **Which Nginx:** Check you're using Homebrew's: `which nginx` and `nginx -V`. Config path: `nginx -T | grep nginx.conf` should show `/opt/homebrew/etc/nginx/nginx.conf`. If not, you may be editing the wrong config.
- **Option A – Homebrew (recommended for prod):**  
  `sudo mkdir -p /opt/homebrew/etc/nginx`  
  First time only (creates file): `sudo htpasswd -c /opt/homebrew/etc/nginx/.htpasswd_openclaw openclaw`  
  To add another user or rotate password (do **not** use `-c` or you overwrite the file): `sudo htpasswd /opt/homebrew/etc/nginx/.htpasswd_openclaw openclaw`  
  Permissions: `sudo chmod 600 /opt/homebrew/etc/nginx/.htpasswd_openclaw`  
  Verify: `ls -la /opt/homebrew/etc/nginx/.htpasswd_openclaw` → owner root/you, mode 600 or 640.  
  In your nginx config: `auth_basic_user_file /opt/homebrew/etc/nginx/.htpasswd_openclaw;`  
  Reload: `sudo nginx -s reload` or `brew services restart nginx`.
- **Option B – Repo (dev only):** `htpasswd -c secrets/.htpasswd_openclaw openclaw`, then in nginx use the **absolute path** to that file. Not recommended for production (path changes per machine; risk of accidental commit).
- On macOS there is no `systemctl`; use `sudo nginx -s reload` or `brew services restart nginx`.

- **Disable (not recommended):** Comment out the two `auth_basic` and `auth_basic_user_file` lines and reload Nginx. Only for local/testing.

**Note:** The browser will prompt for credentials when loading `/openclaw/` (or when the iframe loads). The dashboard page at `/openclaw` is not auth’d by Nginx; only the proxied content is. Same-origin iframe usually reuses the same credentials after the first prompt.

---

## 4. IP allowlist (optional)

In `nginx/dashboard.conf`, inside `location ^~ /openclaw/`, an optional block is commented:

```nginx
# satisfy any;
# allow 1.2.3.4;
# allow 10.0.0.0/8;
# deny all;
```

To restrict access by IP: uncomment, set `allow` to your IPs or CIDR, then reload Nginx. With `satisfy any`, either basic auth OR IP allow can satisfy (adjust to `satisfy all` if you want both).

---

## 5. Test final (después de Basic Auth y reload)

- **Desde terminal:** `curl -I https://dashboard.hilovivo.com/openclaw/` debe devolver `HTTP/1.1 401 Unauthorized` (sin credenciales). Con auth correcta, 200.
- **En el navegador:** Abre https://dashboard.hilovivo.com/openclaw/ → debe pedir usuario/contraseña; sin autenticación no debe cargar contenido. Tras autenticarte, la UI debe cargar y seguir funcionando dentro del iframe en /openclaw.

Si se cumple, la ruta está protegida correctamente.

### Verificación completa (proxy y embedding cerrados)

1. **Sin barra:** `curl -I https://dashboard.hilovivo.com/openclaw` → **301** a `Location: .../openclaw/`
2. **Con barra:** `curl -I https://dashboard.hilovivo.com/openclaw/` → **401**
3. **CSP en navegador:** DevTools → Network → peticiones bajo `/openclaw/` → Response headers deben incluir `Content-Security-Policy: frame-ancestors 'self' https://dashboard.hilovivo.com`

Con eso el embedding en el dashboard queda cerrado y puedes seguir con el primer mandato formal de OpenClaw sobre la trading platform. Detalle en [FIX_OPENCLAW_308_REDIRECT.md](FIX_OPENCLAW_308_REDIRECT.md#verificación-correcta).

---

## 6. Diagnóstico 404 (Next: “This page could not be found”)

Un 404 con mensaje de Next casi siempre significa: Nginx no está interceptando `/openclaw/` y la petición cae en el frontend. Sigue estos pasos en el servidor donde vive dashboard.hilovivo.com.

**1) ¿Nginx tiene cargado el location /openclaw/?**
```bash
sudo nginx -T | grep -n "openclaw"
```
Debe aparecer algo como `location ^~ /openclaw/ { ... }`. Si no aparece, el config no está cargado. Comprueba includes:
```bash
sudo nginx -T | grep -n "include"
```
Confirma que el archivo que contiene `dashboard.conf` (o el server de dashboard) está en el árbol de includes.

**2) ¿El server_name correcto incluye ese location?**
```bash
sudo nginx -T | grep -n "server_name.*dashboard.hilovivo.com"
```
Anota el número de línea. Luego revisa unas líneas antes y después para ver si `location ^~ /openclaw/` está dentro de ese mismo `server { ... }`. Si el location está en otro server block, no se aplicará a dashboard.hilovivo.com.

**3) Interpretar la respuesta desde tu Mac**
```bash
curl -I https://dashboard.hilovivo.com/openclaw/
```
- **404** (y en el navegador mensaje tipo Next “This page could not be found”) → Nginx no está manejando `/openclaw/` (o lo manda al frontend). Objetivo: conseguir **401**, no 404.
- **308** a `/openclaw` (sin barra) → El Nginx **remoto** tiene una redirección por trailing slash (p. ej. `return 308 /openclaw`), **no** el bloque proxy que diseñamos. Hay que desplegar el config correcto en el servidor Ubuntu.
- **401** → Nginx sí lo maneja y Basic Auth está activo.
- **502/504** → Nginx lo maneja, pero el upstream (LAB) no responde.

**Nota:** Si en la respuesta ves `Server: nginx/1.24.0 (Ubuntu)`, el dominio lo sirve un **servidor Ubuntu remoto**. Los cambios de Nginx/htpasswd en tu Mac no afectan a ese servidor; hay que entrar por SSH al servidor del dashboard y trabajar allí.

**4) Si Nginx sí lo maneja (401 o 502), probar upstream desde el servidor**
```bash
curl -I http://52.77.216.100:8080/
```
Si aquí falla: conectividad al LAB (Security Group, NACL, ruta) o el servicio no escucha en 8080 en LAB.

**5) Causas típicas de 404 aunque el config exista**
- El `location /` (u otro location) captura antes porque `/openclaw/` no está en el mismo server block que ese location.
- Estás editando un `dashboard.conf` que no está incluido en el Nginx real (otro sites-enabled, otro path, otra instancia). `nginx -T` muestra la config realmente cargada.

**Dónde ejecutar:** En el **servidor Ubuntu** que sirve dashboard.hilovivo.com (no en tu Mac). Entra por SSH, por ejemplo: `ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147` (o EC2 Instance Connect si SSH falla). En Ubuntu las rutas de Nginx son `/etc/nginx/` (no `/opt/homebrew/`). Recarga con `sudo systemctl reload nginx`.

**Si no hay ningún `location /openclaw` cargado:** El config del repo no está desplegado. Sigue **[DEPLOY_OPENCLAW_NGINX_PROD.md](DEPLOY_OPENCLAW_NGINX_PROD.md)** para añadir el bloque en el servidor, crear htpasswd y recargar.

Si pegas el output de (ejecutados **en el servidor**):
- `sudo nginx -T | grep -n "openclaw"`
- `sudo nginx -T | grep -n "server_name.*dashboard.hilovivo.com"`
- `sudo nginx -T | grep -n "location /openclaw"`
se puede indicar exactamente qué falta y dónde está el fallo.

---

## 7. Troubleshooting

| Symptom | What to check |
|--------|----------------|
| **502 Bad Gateway** | LAB host reachable from the Nginx host? `curl -I http://52.77.216.100:8080/` from the Nginx server. OpenClaw UI process listening on 8080 on LAB? |
| **504 / upstream timeout** | Nginx cannot reach the OpenClaw upstream. See [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md). With only two outputs (dashboard: `curl -s https://ifconfig.me`; OpenClaw host: `sudo ss -lntp | grep ':8080'`), we can tell which branch and the exact next change. |
| **Blank iframe / connection refused** | Same as above; also check that the Nginx server can reach the LAB IP and port (firewall, security groups). See [OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md](OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md). If 504, use [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md). |
| **WebSocket fails (UI not updating)** | Nginx must pass `Upgrade` and `Connection` headers; the config does this. If the UI still fails, confirm the OpenClaw app uses a path that goes through `/openclaw/` (e.g. relative URLs). |
| **CSP / X-Frame-Options: iframe blocked** | The proxy removes upstream `X-Frame-Options` and sets `Content-Security-Policy: frame-ancestors 'self' https://dashboard.hilovivo.com` **always** (including on 401). Use `add_header X-Frame-Options "" always` so Nginx-generated 401 also allows framing. See [OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md](OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md). |
| **Timeouts** | Default proxy timeouts for `/openclaw/` are 300s (send/read). For very long operations, increase in the location block: `proxy_send_timeout 600s;` and `proxy_read_timeout 600s;` then reload. |
| **Basic auth prompt in loop** | Ensure the password file exists and is readable by Nginx. If the iframe and parent are same origin, one auth should suffice; clear site data/cache and try again. |

---

## 8. Security

- Basic auth and/or IP allowlist apply only to `/openclaw/`; they are not global.
- Framing is restricted to `https://dashboard.hilovivo.com` via CSP for the proxied response only; global CSP is not weakened.
- No secrets are committed; the password file lives on the server and is not in the repo.
