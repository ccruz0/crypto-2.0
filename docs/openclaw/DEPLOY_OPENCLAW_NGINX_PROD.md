# Desplegar el bloque /openclaw/ en Nginx de producción

El config del repo no está en el servidor. Opciones: **script automático** (recomendado) o pasos manuales en el servidor.

## Opción A: Script automático (desde tu Mac)

**Siempre ejecutar desde la raíz del repo:**

```bash
cd ~/automated-trading-platform
./scripts/openclaw/deploy_openclaw_nginx_prod.sh
```

**Dry-run (recomendado antes de prod):** no modifica nada en el servidor ni recarga nginx; solo imprime qué haría:

```bash
cd ~/automated-trading-platform
DRY_RUN=1 ./scripts/openclaw/deploy_openclaw_nginx_prod.sh
```

El script: localiza el config de `dashboard.hilovivo.com` (falla si hay 0 o >1 candidatos), comprueba que exista `location / {` en el archivo, hace backup con timestamp, inserta el bloque antes de `location /` (idempotente: si ya existe no inserta), crea `.htpasswd_openclaw` si falta (pide contraseña), ejecuta `nginx -t` y solo entonces `reload`, y comprueba con `curl`.

**Verificación final esperada:**
- `curl -I https://dashboard.hilovivo.com/openclaw` → **301** a `/openclaw/`
- `curl -I https://dashboard.hilovivo.com/openclaw/` → **401** sin auth, **200** en navegador con auth
- En DevTools → Network, respuestas bajo `/openclaw/` deben incluir `Content-Security-Policy: frame-ancestors 'self' https://dashboard.hilovivo.com` (embedding cerrado)

Si ves **308**, ver [FIX_OPENCLAW_308_REDIRECT.md](FIX_OPENCLAW_308_REDIRECT.md) (bloque solo en 80, añadir en 443). Si ves **504**, el upstream no es alcanzable: ver [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md); quick-triage: paste the two outputs from the top of that doc.

El script solo considera **vhosts activos** (`/etc/nginx/sites-enabled/*`), resuelve symlinks y **excluye backups** (`*.bak.*`, `*.backup`, `*~`). Los backups se guardan en **`/etc/nginx/backups/`** (no en `sites-enabled`) para evitar "duplicate default server". Si el script falla con "htpasswd: command not found", en el servidor: `sudo apt-get install -y apache2-utils` y vuelve a ejecutar.

---

## Opción B: Pasos manuales en el servidor

Sigue estos pasos **en el servidor Ubuntu** (SSH o EC2 Instance Connect).

---

## 1. Localizar el config activo

```bash
# Ver qué archivos carga Nginx
ls -la /etc/nginx/sites-available
ls -la /etc/nginx/sites-enabled

# Ver el server block de dashboard (ajusta el rango si hace falta)
sudo nginx -T | sed -n '260,360p'
```

El `server_name dashboard.hilovivo.com;` estará en un archivo bajo `sites-available`, enlazado desde `sites-enabled` (p. ej. `dashboard` o `default`). Edita ese archivo.

---

## 2. Añadir el bloque ANTES de `location /`

Abre el archivo (p. ej. `sudo nano /etc/nginx/sites-available/dashboard`). Dentro del `server { ... }` que tiene `server_name dashboard.hilovivo.com;`, añade **justo antes** de `location / {` este bloque (igual que en `nginx/dashboard.conf` del repo):

```nginx
    # OpenClaw Web UI (LAB) – proxy to LAB instance; basic auth; allow iframe from dashboard only
    location ^~ /openclaw/ {
        proxy_pass http://52.77.216.100:8080/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_cache_bypass $http_upgrade;

        proxy_connect_timeout 30s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;

        proxy_hide_header X-Frame-Options;
        proxy_hide_header Content-Security-Policy;
        add_header Content-Security-Policy "frame-ancestors 'self' https://dashboard.hilovivo.com" always;

        auth_basic "OpenClaw";
        auth_basic_user_file /etc/nginx/.htpasswd_openclaw;

        proxy_intercept_errors on;
        error_page 502 503 504 = @frontend_error;
    }
```

Si en el servidor no existe `@frontend_error`, quita las dos últimas líneas (`proxy_intercept_errors on;` y `error_page ...`) o define ese named location como en el repo (handler que devuelve 503 HTML).

Guarda y cierra.

---

## 3. Crear htpasswd en el servidor

```bash
sudo htpasswd -c /etc/nginx/.htpasswd_openclaw openclaw
# Introduce la contraseña cuando pida

sudo chmod 600 /etc/nginx/.htpasswd_openclaw
```

---

## 4. Probar y recargar Nginx

```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## 5. Comprobar

Desde tu Mac (o desde el servidor):

```bash
curl -I https://dashboard.hilovivo.com/openclaw/
```

**Esperado:** `401 Unauthorized`. No 404, no 308.

Luego en el navegador: https://dashboard.hilovivo.com/openclaw/ → debe pedir usuario/contraseña; tras autenticarte, la UI de OpenClaw debe cargar.

---

## Troubleshooting

| Problema | Causa / solución |
|----------|-------------------|
| **`nginx -t` → "duplicate default server"** | Había un backup (p. ej. `default.bak.*`) dentro de `sites-enabled`, así que nginx cargaba dos server blocks. En el servidor: `sudo rm -f /etc/nginx/sites-enabled/*.bak.*` y `sudo nginx -t && sudo systemctl reload nginx`. Desde la versión actual del script, los backups van a `/etc/nginx/backups/` y no se cargan. |
| **"More than one config file matches"** | Varios archivos en `sites-enabled` tienen `server_name dashboard.hilovivo.com`. Deja solo el vhost activo; mueve o elimina backups de `sites-enabled`: `ls /etc/nginx/sites-enabled/`. |
| **`htpasswd: command not found`** | En el servidor: `sudo apt-get update -qq && sudo apt-get install -y apache2-utils`. Luego crea el archivo: `sudo htpasswd -c /etc/nginx/.htpasswd_openclaw openclaw` y vuelve a ejecutar el script. |

---

## Resumen

| Paso | Acción |
|------|--------|
| 1 | Localizar archivo en `sites-available` / `sites-enabled` |
| 2 | Añadir `location ^~ /openclaw/ { ... }` **antes** de `location /` |
| 3 | `sudo htpasswd -c /etc/nginx/.htpasswd_openclaw openclaw` |
| 4 | `sudo nginx -t && sudo systemctl reload nginx` |
| 5 | `curl -I https://dashboard.hilovivo.com/openclaw/` → 401 |

**Referencia:** El bloque completo (con comentarios) está en el repo en `nginx/dashboard.conf`, líneas 61–97. Puedes copiarlo de ahí si prefieres.
