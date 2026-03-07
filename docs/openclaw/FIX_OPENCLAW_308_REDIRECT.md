# Arreglar 308/404 en /openclaw — diagnóstico mecánico

Sin suposiciones. Sigue los pasos en orden en el servidor **52.220.32.147**.

### 1-Minute Fix (443 block missing)

On Dashboard host:

```bash
git pull origin main
sudo ./scripts/openclaw/insert_nginx_openclaw_block.sh <OPENCLAW_PRIVATE_IP>
```

Verify:

- `/openclaw` → 301
- `/openclaw/` → 401

If 504 → follow [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md).

Short. Mechanical. No theory.

---

## 1) Confirmar qué server block 443 atiende dashboard.hilovivo.com

En el servidor:

```bash
sudo nginx -T 2>/dev/null | grep -nE "server_name dashboard\.hilovivo\.com|listen 443|location = /openclaw|location \^~ /openclaw/"
```

**Qué quieres ver** (dentro del mismo `server { ... }` de 443, en ese orden de líneas):

- `server_name dashboard.hilovivo.com;`
- `listen 443` (o `listen [::]:443`)
- `location = /openclaw { ... }`
- `location ^~ /openclaw/ { ... }`
- y luego `location / {` con `proxy_pass http://127.0.0.1:3000;`

Si **no** aparecen esas dos `location` de openclaw en el 443, todavía no están en el sitio correcto.

---

## 2) Imprimir solo el server 443 completo (prueba final)

```bash
sudo nginx -T 2>/dev/null | sed -n '/server_name dashboard.hilovivo.com/,/^}/p'
```

Pega esa salida si quieres que te digan la línea exacta donde insertar el bloque.

---

## 3) Si falta, insertar el bloque en el 443 correcto

**Archivo real** (target del symlink):

```bash
readlink -f /etc/nginx/sites-enabled/default
```

**Editar ese archivo:**

```bash
sudo nano "$(readlink -f /etc/nginx/sites-enabled/default)"
```

Dentro del **server de 443** (el que tiene `listen 443 ssl` y `server_name dashboard.hilovivo.com`), pega **justo antes** de:

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
```

**este bloque:**

```nginx
location = /openclaw {
    return 301 /openclaw/;
}

location ^~ /openclaw/ {
    auth_basic "OpenClaw";
    auth_basic_user_file /etc/nginx/.htpasswd_openclaw;

    proxy_pass http://<OPENCLAW_PRIVATE_IP>:8080/;   # v1.1: use private IP (e.g. 172.31.x.x), not public

    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_cache_bypass $http_upgrade;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_connect_timeout 30s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;

    proxy_hide_header X-Frame-Options;
    add_header Content-Security-Policy "frame-ancestors 'self' https://dashboard.hilovivo.com" always;
    add_header X-Frame-Options "" always;
}
```

Guarda y cierra. No borres nada más.

---

## 4) Recarga y verifica con 2 curls

```bash
sudo nginx -t && sudo systemctl reload nginx
```

```bash
curl -I https://dashboard.hilovivo.com/openclaw
curl -I https://dashboard.hilovivo.com/openclaw/
```

**Esperado:**

- `/openclaw` → **301** a `/openclaw/`
- `/openclaw/` → **401** (Basic Auth)

Si ves **504** (upstream timeout), el proxy está bien pero OpenClaw no es alcanzable: ver [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md). Quick-triage: paste the two outputs from the top of that doc.

---

## 5) Si sigue 404 en el navegador

Pega la salida de:

```bash
sudo nginx -T 2>/dev/null | sed -n '/server_name dashboard.hilovivo.com/,/^}/p'
```

y con eso se indica la línea exacta donde insertar en una pasada.

---

## Verificación completa (embedding cerrado)

Una vez 401/301 correctos:

1. **Sin barra:** `curl -I https://dashboard.hilovivo.com/openclaw` → **301** a `.../openclaw/`
2. **Con barra:** `curl -I https://dashboard.hilovivo.com/openclaw/` → **401**
3. **CSP en navegador:** DevTools → Network → peticiones bajo `/openclaw/` → Response headers con `Content-Security-Policy: frame-ancestors 'self' https://dashboard.hilovivo.com`

Con eso el embedding en el dashboard queda cerrado.
