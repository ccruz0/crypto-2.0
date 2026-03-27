# NGINX: proxy /openclaw/ to LAB private IP

## Goal
Make PROD proxy `/openclaw/` to LAB OpenClaw over the VPC private IP.

## Facts
- **PROD** (atp-rebuild-2026): instance **i-087953603011543c5**, private IP 172.31.32.169 — runs Nginx + dashboard. **Run the script here.**
- **LAB** (atp-lab-ssm-clean): instance **i-0d82c172235770a0d**, private IP 172.31.3.214 — runs OpenClaw on **8081** (container `-p 8081:18789`). Do not run the Nginx script on LAB.
- LAB OpenClaw: http://172.31.3.214:8081/ returns HTTP 200
- PROD nginx site file: `/etc/nginx/sites-enabled/default` (or `dashboard.conf` on some setups)
- Current issue: proxy_pass points to old public IP 52.77.216.100

## Minimal diff
Replace:
- `proxy_pass http://52.77.216.100:8080/;` or `...8080/`
with:
- `proxy_pass http://172.31.3.214:8081/;` (LAB container listens on host port 8081)

---

## Deploy and verify (step-by-step)

Run these on the **PROD** instance (i-087953603011543c5). If SSM is unavailable, use EC2 Instance Connect or SSH (e.g. `ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147`).

### 1. Connect

From your Mac (SSM):
```bash
aws ssm start-session --target i-087953603011543c5 --region ap-southeast-1
```

If you get "Connection lost" or "Undeliverable": EC2 Console → Instances → atp-rebuild-2026 → Connect → **EC2 Instance Connect** (browser shell).

### 2. Go to the repo

```bash
cd /home/ubuntu/crypto-2.0
```

If that fails:
```bash
sudo find / -maxdepth 4 -type d -name automated-trading-platform 2>/dev/null
```
Then `cd` into the path it returns.

### 3. Pull latest code

```bash
git config --global --add safe.directory /home/ubuntu/crypto-2.0
git pull origin main
```

### 4. Run the OpenClaw proxy fix script

```bash
bash scripts/openclaw/fix_openclaw_proxy_prod.sh
```

If your Nginx site file is `dashboard.conf` (not `default`):
```bash
NGINX_SITE=/etc/nginx/sites-enabled/dashboard.conf bash scripts/openclaw/fix_openclaw_proxy_prod.sh
```

You should see: creating `/etc/nginx/backups`, moving old `.bak` files (if any), timestamped backup, `nginx -t`, reload.

### 5. Verify Nginx config

```bash
sudo nginx -t
```
Expected: `syntax is ok` / `test is successful`

### 6. Test OpenClaw locally on PROD

```bash
curl -I http://localhost/openclaw/
```
Expected: `HTTP/1.1 401 Unauthorized` and `WWW-Authenticate: Basic realm="OpenClaw"`

### 7. Test from browser

Open: https://dashboard.hilovivo.com/openclaw/  
Login: user `admin`, password = your htpasswd password.

### 8. Confirm Nginx loaded the block

```bash
sudo nginx -T | grep -n openclaw
```
You should see the `location` block.

---

## Short form (idempotent script)

On PROD shell:
```bash
cd /home/ubuntu/crypto-2.0
git pull origin main
bash scripts/openclaw/fix_openclaw_proxy_prod.sh
```

## Expected verification
- From PROD:
  - `curl -I http://172.31.3.214:8080/` → HTTP 200
- From anywhere:
  - `curl -I https://dashboard.hilovivo.com/openclaw/` → HTTP 401 (Basic Auth)

---

## Verify OpenClaw is working (full checklist)

### 1. What “working” means (PROD)

- **https://dashboard.hilovivo.com/openclaw/** loads
- You get a **Basic Auth** prompt
- After login, you see the **OpenClaw UI** (proxied to LAB)

### 2. Verify LAB OpenClaw is up

On the **LAB** instance (i-0d82c172235770a0d):

```bash
docker ps
curl -I http://localhost:8081/
```

Expected: container `openclaw` running; curl returns **200** or **302** (not connection refused).  
If LAB doesn’t respond locally, Nginx on PROD can’t fix that.

### 3. Verify PROD can reach LAB (private IP + port)

On the **PROD** instance (i-087953603011543c5):

- LAB private IP: **172.31.3.214** (OpenClaw port **8081**)
- Test from PROD:

```bash
curl -m 3 -I http://172.31.3.214:8081/
```

If this times out or refuses → network/security group, not Nginx.

**AWS requirements:**

- LAB security group **inbound**: source = PROD security group (or PROD private IP), port **8081** TCP
- NACLs allow traffic (rarely the issue)

### 4. Verify Nginx on PROD points to the right upstream

On PROD:

```bash
sudo nginx -T | grep -n "location /openclaw"
sudo nginx -T | grep -n "proxy_pass" | grep -i openclaw
```

You should see `proxy_pass http://172.31.3.214:8081/;` (or the correct LAB IP/port). If it points to a wrong IP/port, fix that first (e.g. run `fix_openclaw_proxy_prod.sh`).

### 5. Verify path rewrite

On PROD:

```bash
curl -I http://localhost/openclaw/
```

**Pattern A (strip prefix)** — usual:

- `location /openclaw/ { proxy_pass http://LAB:PORT/; }`  
  → request `/openclaw/` goes to LAB as `/`

**Pattern B (keep prefix):**

- `location /openclaw/ { proxy_pass http://LAB:PORT; }`  
  → only works if the app is configured with base path `/openclaw`

Most UIs expect Pattern A.

### 6. Headers that break apps (WebSockets)

If OpenClaw uses WebSockets, the Nginx block may need:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

Without these, the page may load but actions fail.

### 7. Nginx error and access logs (fastest signal)

On PROD:

```bash
sudo tail -n 200 /var/log/nginx/error.log
sudo tail -n 200 /var/log/nginx/access.log | grep openclaw
```

Interpretation:

- `connect() failed (113: No route to host)` → SG/NACL/routing
- `connection refused` → LAB not listening / wrong port
- `404 from upstream` → wrong path rewrite / base path mismatch
- `401` → Basic Auth is working (good)

---

### Six outputs to paste (run on PROD)

Run these **on the PROD instance** and paste the outputs for diagnosis:

```bash
# 1) openclaw location block from active config
sudo nginx -T | sed -n '/location \/openclaw/,/}/p'

# 2) local openclaw response
curl -I http://localhost/openclaw/

# 3) PROD → LAB connectivity (LAB private IP :8081)
curl -m 3 -I http://172.31.3.214:8081/

# 4) last nginx errors
sudo tail -n 80 /var/log/nginx/error.log

# 5) nginx listen sockets
sudo ss -lntp | grep nginx || true

# 6) confirm (for your paste): LAB private IP = 172.31.3.214, OpenClaw port = 8081
echo "LAB_PRIVATE_IP=172.31.3.214 OPENCLAW_PORT=8081"
```

With those six outputs, the fix is usually one of: open LAB SG from PROD SG, correct `proxy_pass` target, add trailing slash to strip `/openclaw/`, or add WebSocket headers.

**If the page loads but shows "Placeholder" or the console reports "WebSocket connection to 'ws://localhost:8081/' failed":** see [OPENCLAW_PLACEHOLDER_AND_WEBSOCKET.md](../openclaw/OPENCLAW_PLACEHOLDER_AND_WEBSOCKET.md) (placeholder = deploy real OpenClaw image on LAB; WebSocket = app must use same-origin or env WebSocket URL, not localhost).

### Decision tree (after you have the outputs)

| Check | If it fails / looks wrong | Action |
|-------|---------------------------|--------|
| **(c)** `curl -m 3 -I http://172.31.3.214:8081/` | Timeout, connection refused, no 200 | **Networking:** LAB SG must allow TCP 8081 from PROD (SG or PROD private IP 172.31.32.169). Fix SG, then retest (c). |
| **(a)** No `location /openclaw` or wrong `proxy_pass` | Missing block or `proxy_pass` not to 172.31.3.214:8081 | **Nginx config:** Run `bash scripts/openclaw/fix_openclaw_proxy_prod.sh` (or set `NGINX_SITE=...` if site file is not default); ensure script uses port 8081. |
| **(b)** `curl localhost/openclaw/` not 401 | 502, 504, 404 | If (c) is OK: fix path/rewrite and/or add WebSocket headers in the `location /openclaw/` block (see Step 6 in checklist). |
| **(d)** error.log | `connect() failed`, `upstream refused` | Use (c) and (a) to fix upstream reachability and `proxy_pass`. |

After any change: `sudo nginx -t && sudo systemctl reload nginx`, then `curl -I http://localhost/openclaw/` (expect 401).

**When PROD SSM is Undeliverable:** Connect via EC2 Instance Connect or SSH (e.g. `ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147`), then from the repo run:

```bash
cd /home/ubuntu/crypto-2.0
git pull origin main
bash scripts/openclaw/diagnose_openclaw_prod.sh
```

Paste the full output for diagnosis.

---

## If it fails
- Inspect nginx errors:

```bash
sudo tail -n 120 /var/log/nginx/error.log
```

- Check LAB reachability from PROD:

```bash
curl -sS -m 5 -I http://172.31.3.214:8081/ | head -n 20
```

- Roll back using the backup path printed by the script, e.g.:
  `sudo cp -a /etc/nginx/backups/default.bak.YYYY-MM-DD-HHMM /etc/nginx/sites-enabled/default && sudo nginx -t && sudo systemctl reload nginx`

## Nota: dos bloques /openclaw/ en PROD

Si en PROD tienes dos bloques `location ^~ /openclaw/`, el script reemplaza **todas** las ocurrencias de `proxy_pass http://52.77.216.100:8080/;` por la IP privada. Después de que funcione, lo correcto es dejar un solo bloque (p. ej. el del server 443 con /api y / bien configurados) y eliminar el duplicado. Ver siguiente paso para parche mínimo.
