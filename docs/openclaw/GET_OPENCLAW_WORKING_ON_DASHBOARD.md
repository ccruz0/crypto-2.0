# Get OpenClaw working on the dashboard

Ordered checklist. Do **OpenClaw host** first, then **Dashboard host**, then **browser**.

---

## 1. OpenClaw host (LAB)

- [ ] OpenClaw is running and listening on **0.0.0.0:8080** (not only 127.0.0.1).

  On the OpenClaw instance:
  ```bash
  docker compose -f docker-compose.openclaw.yml up -d
  sudo ss -lntp | grep ':8080'
  ```
  You want `0.0.0.0:8080`. If not, fix the service bind (see [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md)).

- [ ] Get the **private IP** of the OpenClaw host (you’ll need it on the Dashboard):

  ```bash
  hostname -I
  # or
  curl -s http://169.254.169.254/latest/meta-data/local-ipv4
  ```
  Use that as `<OPENCLAW_PRIVATE_IP>` below.

- [ ] **Security group:** Dashboard must be able to reach OpenClaw on port **8080**.  
  OpenClaw’s SG → Inbound → add rule: **Custom TCP 8080**, source = **Dashboard instance’s security group** (or VPC CIDR).  
  See [OPENCLAW_PRIVATE_NETWORK_MIGRATION.md](OPENCLAW_PRIVATE_NETWORK_MIGRATION.md) §4.

- [ ] From the **Dashboard host**, confirm reachability (replace with real IP):
  ```bash
  curl -sv --max-time 5 http://<OPENCLAW_PRIVATE_IP>:8080/
  ```
  Expect HTTP 200/302/401. Timeout → fix SG or network.

---

## 2. Dashboard host

- [ ] **Basic auth file** exists. If missing, Nginx will fail on reload:

  ```bash
  sudo htpasswd -c /etc/nginx/.htpasswd_openclaw openclaw
  ```
  (Enter password when prompted.)

- [ ] **Insert the Nginx OpenClaw block** (run on Dashboard):

  ```bash
  cd ~/automated-trading-platform || cd /home/ubuntu/crypto-2.0
  git pull origin main
  ls scripts/openclaw/insert_nginx_openclaw_block.sh   # confirm script exists
  sudo ./scripts/openclaw/insert_nginx_openclaw_block.sh <OPENCLAW_PRIVATE_IP>
  ```

  You should see: backup created, block inserted (or “already present”), `nginx -t` OK, reload OK.

- [ ] **Verify** (on Dashboard or from your machine):

  ```bash
  curl -I https://dashboard.hilovivo.com/openclaw      # expect 301
  curl -I https://dashboard.hilovivo.com/openclaw/     # expect 401
  ```

  - **404** → block not in the 443 server; see [FIX_OPENCLAW_308_REDIRECT.md](FIX_OPENCLAW_308_REDIRECT.md).
  - **504** → upstream not reachable; see [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md).

---

## 3. Frontend (if not already deployed)

- [ ] Dashboard frontend includes the `/openclaw` route (iframe to `/openclaw/`).  
  Repo already has `frontend/src/app/openclaw/page.tsx`. Deploy the frontend so that route is live.

---

## 4. Browser

- [ ] Open **https://dashboard.hilovivo.com/openclaw**.
- [ ] When prompted, enter the Basic Auth user/password (same as `.htpasswd_openclaw`).
- [ ] OpenClaw UI should load in the iframe (or use “Open in new tab” if needed).

---

## Quick links

| Problem | Doc |
|--------|-----|
| 404 / block missing | [FIX_OPENCLAW_308_REDIRECT.md](FIX_OPENCLAW_308_REDIRECT.md) (1-Minute Fix) |
| 504 / upstream timeout | [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md) |
| Iframe blank after auth | [OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md](OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md) |
| First run / calibration | [OPENCLAW_FIRST_RUN.md](OPENCLAW_FIRST_RUN.md) |
