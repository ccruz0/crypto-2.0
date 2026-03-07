# Apply OpenClaw Nginx 8081 Fix on PROD

**Purpose:** Fix 502/504 at https://dashboard.hilovivo.com/openclaw/ by pointing Nginx to LAB port **8081** (OpenClaw container) instead of 8080, and ensure the WebSocket proxy forwards to backend path **/ws** (not /).

**Instance:** PROD `i-087953603011543c5` (dashboard.hilovivo.com).

**504 on /openclaw/ws:** If you see 504 Gateway Time-out when the app connects to `wss://dashboard.hilovivo.com/openclaw/ws`, ensure the Nginx block for `location = /openclaw/ws` uses `proxy_pass http://172.31.3.214:8081/ws;` (path `/ws`) so the backend receives the WebSocket upgrade on `/ws`. The canonical config is in this repo: `nginx/dashboard.conf`.

**Console "ws://localhost:8081 failed":** The OpenClaw frontend (repo ccruz0/openclaw) must build the WebSocket URL from the current origin (e.g. `wss://dashboard.hilovivo.com/openclaw/ws`), not `ws://localhost:8081`. Fix in openclaw repo: `getOpenClawWsUrl()` / `ws-url.ts` and rebuild the image.

**504 + "Empty reply from server" / curl returns 000:** If the gateway inside the container listens only on `127.0.0.1:18789`, traffic forwarded by Docker (`-p 8081:18789`) never reaches the process. In repo ccruz0/openclaw the gateway must **bind to `0.0.0.0`** when running in Docker (e.g. via env `HOST=0.0.0.0` or equivalent), then rebuild the image and redeploy on LAB. Check logs: `[gateway] listening on ws://127.0.0.1:18789` → should be `ws://0.0.0.0:18789` in container.

---

## Option 0: Script (tries SSM; if Undeliverable, prints manual steps)

From the repo root:

```bash
./scripts/openclaw/apply_nginx_8081_prod.sh
```

---

## Option 1: SSM Session Manager (interactive)

1. Connect to PROD:
   ```bash
   aws ssm start-session --target i-087953603011543c5 --region ap-southeast-1
   ```

2. On the PROD shell, run (paste the full block):
   ```bash
   set -e
   for f in /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/dashboard.conf; do
     [ -f "$f" ] && sudo sed -i 's/172.31.3.214:8080/172.31.3.214:8081/g' "$f" && echo "Updated $f"
   done
   # WebSocket: first 8081/; -> 8081/ws; so backend receives path /ws (fixes 504 on /openclaw/ws)
   [ -f /etc/nginx/sites-enabled/dashboard.conf ] && sudo sed -i '0,/172\.31\.3\.214:8081\/;/s/172\.31\.3\.214:8081\/;/172.31.3.214:8081\/ws;/' /etc/nginx/sites-enabled/dashboard.conf && echo "Updated WS path"
   sudo nginx -t && sudo systemctl reload nginx
   echo "Done. Test: curl -sI https://dashboard.hilovivo.com/openclaw/"
   ```

3. In the browser, open https://dashboard.hilovivo.com/openclaw/ — you should see the OpenClaw UI, not 502.

---

## Option 2: One-line sed (if config is in default only)

```bash
sudo sed -i 's/172.31.3.214:8080/172.31.3.214:8081/g' /etc/nginx/sites-enabled/default && sudo nginx -t && sudo systemctl reload nginx
```

---

## Option 3: Run fix script from repo (if you have the repo on PROD)

```bash
cd /home/ubuntu/automated-trading-platform
./scripts/openclaw/fix_openclaw_proxy_prod.sh
```

---

## Fix 504 on /openclaw/ws (WebSocket path)

If the UI loads but the WebSocket gets 504, the proxy for `/openclaw/ws` may be sending the request to backend path `/` instead of `/ws`. On PROD, ensure the block for `location = /openclaw/ws` contains:

- `proxy_pass http://172.31.3.214:8081/ws;` (must end with `/ws`, not `/`)
- `proxy_connect_timeout 60s;` (optional but recommended)

Edit the active Nginx config (e.g. `/etc/nginx/sites-enabled/dashboard.conf`), then run `sudo nginx -t && sudo systemctl reload nginx`. Or copy the full `nginx/dashboard.conf` from this repo to PROD and reload.

---

## Note

`aws ssm send-command` to this instance may show **Undeliverable** (command never reaches the agent). Use an **interactive** SSM session (Option 1) or SSH to run the commands above.
