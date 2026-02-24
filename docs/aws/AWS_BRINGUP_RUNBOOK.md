# AWS Bring-Up Runbook

Single runbook for bringing the AWS trading stack to a "works perfectly" state on an EC2 instance. Repo path on the instance: **~/crypto-2.0** (adjust if your path differs).

---

### Dashboard not loading? Start here

| Symptom | Go to |
|--------|--------|
| Don’t know where it breaks | **C3)** Run A (laptop) + B (EC2), paste outputs |
| DNS wrong (instance IP ≠ DNS A record) | **C3)** “DNS points to the wrong IP” → update A record, then Elastic IP |
| HTTPS fails (SSL_ERROR_SYSCALL), DNS OK | **C3)** “When DNS is OK but HTTPS fails” → **Fork 1** (Case A/B/C) |
| Can’t SSH (80/443 open, 22 blocked) | **C3)** “SSH blocked” → Path 1 (SG) or Path 2 (SSM) |
| Backend/containers/nginx on instance | **C2)** “Run this on EC2 and paste” + “One-command fixes” |

---

## A) Operator script (copy-paste safe)

Run these commands on the EC2 instance in order. Start from a clean shell.

```bash
# --- 1) Establish environment ---
cd ~/crypto-2.0

# --- 2) Diagnostics (capture output for troubleshooting) ---
echo "=== Host ==="
hostname
curl -4 -sS --connect-timeout 5 ifconfig.me 2>/dev/null || echo "no-egress"
echo ""
echo "=== Git ==="
git status --short
echo "=== Docker Compose ==="
docker compose version
docker compose config --profiles
docker compose --profile aws config --services
echo "=== Env / secrets presence (paths only) ==="
ls -la .env .env.aws .env.local 2>/dev/null || true
ls -la secrets/ 2>/dev/null || true
echo "=== Containers ==="
docker compose --profile aws ps 2>/dev/null || true
docker ps -a --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || true
echo "=== Networks ==="
docker network ls 2>/dev/null || true

# --- 3) Prerequisites: required files ---
# Ensure .env and .env.aws exist; .env.aws must contain TELEGRAM_BOT_TOKEN_ENCRYPTED and TELEGRAM_CHAT_ID (no plaintext TELEGRAM_BOT_TOKEN).
# Ensure secrets/telegram_key exists (copy of the key file used to create TELEGRAM_BOT_TOKEN_ENCRYPTED, e.g. from setup_telegram_token.py).
if [ ! -f .env ]; then echo "ERROR: .env missing. Create from .env.example."; exit 1; fi
if [ ! -f .env.aws ]; then echo "ERROR: .env.aws missing. Create from ops/atp.env.template."; exit 1; fi
if [ ! -f secrets/telegram_key ]; then echo "ERROR: secrets/telegram_key missing. Copy .telegram_key (from setup_telegram_token.py) to secrets/telegram_key on this host."; exit 1; fi
chmod 600 secrets/telegram_key 2>/dev/null || true

# --- 4) Render runtime.env (required for backend-aws and market-updater-aws) ---
bash scripts/aws/render_runtime_env.sh
if [ ! -f secrets/runtime.env ]; then echo "ERROR: secrets/runtime.env missing after render."; exit 1; fi

# --- 5) Optional: DB password file (if compose uses it) ---
if [ ! -f secrets/pg_password ]; then
  echo "WARNING: secrets/pg_password not found. Ensure POSTGRES_PASSWORD is set in .env or .env.aws."
fi

# --- 6) Validate compose (no config output) ---
bash scripts/aws/check_no_inline_secrets_in_compose.sh
bash scripts/aws/safe_compose_check.sh

# --- 7) Build and start AWS stack ---
docker compose --profile aws up -d --build

# --- 8) Wait for health ---
echo "Waiting 30s for services to become healthy..."
sleep 30

# --- 9) Service status ---
docker compose --profile aws ps

# --- 10) Health checks ---
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/health && echo " backend /health" || echo " backend /health FAIL"
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/api/health && echo " backend /api/health" || echo " backend /api/health FAIL"
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/ping_fast && echo " backend /ping_fast" || echo " backend /ping_fast FAIL"

# --- 11) If nginx is installed on host, restart it to pick up backend ---
sudo systemctl restart nginx 2>/dev/null || true

# --- 12) Optional: test Telegram from running backend (no token in output) ---
# Uses diagnostics endpoint; requires ENABLE_DIAGNOSTICS_ENDPOINTS=1 and valid DIAGNOSTICS_API_KEY in secrets/runtime.env.
# curl -sS -X POST "http://127.0.0.1:8002/api/diagnostics/telegram-test" -H "X-API-Key: YOUR_DIAG_KEY" 2>/dev/null || echo "Telegram test skipped (set DIAGNOSTICS_API_KEY and use internal test endpoint if available)"
echo "Done. See Verification section below for full checklist."
```

---

## B) Minimal code/config changes (already applied in repo)

| File | Change | Why |
|------|--------|-----|
| `backend/app/core/telegram_secrets.py` | Read `TELEGRAM_BOT_TOKEN_ENCRYPTED` from `os.environ`; use `TELEGRAM_KEY_FILE` env for key path; permission check only when key file exists | Backend in Docker gets token from `secrets/runtime.env` (env), not from a file; key file is mounted at `/run/secrets/telegram_key`. |
| `scripts/aws/render_runtime_env.sh` | Output only `TELEGRAM_BOT_TOKEN_ENCRYPTED` (and `TELEGRAM_CHAT_ID`, admin/diag keys); require encrypted token from SSM or `.env.aws` | No plaintext Telegram token in any env or compose file. |
| `docker-compose.yml` | `backend-aws` and `market-updater-aws`: add `TELEGRAM_KEY_FILE=/run/secrets/telegram_key` and volume `./secrets/telegram_key:/run/secrets/telegram_key:ro` | Backend and market-updater need the key file to decrypt the token. |
| `ops/atp.env.template` | Replace plaintext `TELEGRAM_BOT_TOKEN*` with `TELEGRAM_BOT_TOKEN_ENCRYPTED` and instructions | Template must not reference plaintext token. |
| `scripts/aws/safe_compose_check.sh` | New script: validate compose with `--profile aws` without printing config | Avoid leaking secrets; referenced by deploy_aws.sh. |
| `docs/runbooks/secrets_runtime_env.md` | Document `TELEGRAM_BOT_TOKEN_ENCRYPTED` in runtime.env | Align docs with encrypted-token-only flow. |

---

## C) Verification

Run these on the instance after bring-up. All should pass.

```bash
cd ~/crypto-2.0

# 1) All essential services Up (healthy)
docker compose --profile aws ps
# Expect: db, backend-aws, frontend-aws (if built), market-updater-aws, and optionally prometheus/grafana with state "Up" or "Up (healthy)".

# 2) Backend health
curl -sS http://127.0.0.1:8002/health
# Expect: {"status":"ok"}

curl -sS http://127.0.0.1:8002/api/health
# Expect: {"status":"ok","path":"/api/health"}

curl -sS http://127.0.0.1:8002/ping_fast
# Expect: {"status":"ok","source":"ping_fast"}

# 3) System health (DB + telegram status)
curl -sS http://127.0.0.1:8002/api/health/system
# Expect: JSON with db_status, telegram.enabled, etc. (200 OK).

# 4) If nginx is fronting the app (public access)
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1/
# Expect: 200 (or 301/302 if redirect). If using domain, test the same against the public URL.

# 5) Telegram test (from instance, no token in chat)
# Option A: If your backend exposes a guarded test endpoint (e.g. /api/diagnostics/telegram-test with X-API-Key), call it.
# Option B: From repo root on the instance, run (uses encrypted token from env):
#   python3 scripts/send_telegram_test_minimal.py
# You must have .env or .env.aws with TELEGRAM_BOT_TOKEN_ENCRYPTED and TELEGRAM_CHAT_ID, and .telegram_key or TELEGRAM_KEY_FILE pointing to secrets/telegram_key.
# Expect: "Mensaje de prueba enviado a Telegram" or similar success.

# 6) No secrets committed
git status
# Expect: no staged or unstaged changes that add secrets; secrets/ and .env* are gitignored.
```

---

## C2) EC2 systematic verification (AWS dashboard behind nginx)

Use this order on the EC2 instance to pinpoint where things break. **Nginx runs on the host** (not in Docker); the compose stack is backend, frontend, market-updater, db.

### 1️⃣ Is the backend alive?

```bash
cd ~/crypto-2.0
curl -sS http://127.0.0.1:8002/health
# Expected: {"status":"ok"}

curl -sS http://127.0.0.1:8002/api/health
# Expected: {"status":"ok","path":"/api/health"}
```

If either fails → backend is down. Check `docker compose --profile aws logs backend-aws`.

---

### 2️⃣ Are containers running?

```bash
docker compose --profile aws ps
```

You should see:

| Service            | Expected state     |
|--------------------|--------------------|
| **backend-aws**    | Up (healthy)       |
| **frontend-aws**   | Up                 |
| **market-updater-aws** | Up            |
| **db** (postgres_hardened) | Up (healthy) |
| *(optional)* prometheus, grafana, etc. | Up |

**Note:** Nginx is **not** in this compose stack; it runs on the host (`systemctl status nginx`). If frontend-aws or db is not Up → that’s your issue.

---

### 3️⃣ Is nginx responding?

Nginx runs on the **host**, not in Docker.

```bash
curl -I http://localhost
# Expected: HTTP/1.1 200 or 301/302
```

If not → nginx not running or misconfigured.

**Restart nginx (host):**
```bash
sudo systemctl restart nginx
# Check
sudo systemctl status nginx
```

---

### 4️⃣ Check domain resolution

From your **local machine** (not EC2):

```bash
nslookup dashboard.hilovivo.com
```

It must resolve to your EC2 public IP. If it doesn’t → DNS issue (fix at your DNS provider).

---

### 5️⃣ If the page loads but is blank

Usually:

- Frontend built but API not reachable (backend down or wrong URL)
- Wrong `NEXT_PUBLIC_API_URL` (frontend should use `/api` so nginx can proxy)
- CORS or gateway mismatch

Check browser DevTools → Console and Network for errors.

---

### What “working” looks like

You can say the dashboard is working when **all** of this is true:

**From EC2:**

- `curl -sS http://127.0.0.1:8002/health` → `{"status":"ok"}`
- `docker compose --profile aws ps` shows **frontend-aws** Up and **backend-aws** Up (healthy)
- `curl -I http://localhost` → **200** or a redirect (3xx)

**From your laptop:**

- `nslookup dashboard.hilovivo.com` resolves to the EC2 public IP
- Loading the site returns HTML, then JS loads with **no console errors**

---

### Run this on EC2 and paste the output

```bash
cd ~/crypto-2.0
echo "=== Containers ==="
docker compose --profile aws ps
echo ""
echo "=== Backend /health ==="
curl -sS http://127.0.0.1:8002/health
echo ""
echo "=== Backend /api/health ==="
curl -sS http://127.0.0.1:8002/api/health
echo ""
echo "=== Nginx (host) ==="
curl -I http://localhost
echo ""
echo "=== Frontend via host nginx ==="
curl -sS -I http://localhost/ | head -n 5
echo ""
echo "=== Backend via host nginx (/api/health) ==="
curl -sS http://localhost/api/health
```

**What you expect:**

- `http://localhost/` → **200** (or 301/302)
- `http://localhost/api/health` → `{"status":"ok","path":"/api/health"}`

This isolates:

- **Backend OK but nginx not proxying /api** → 127.0.0.1:8002/api/health OK, localhost/api/health fails
- **Frontend container OK but nginx not serving /** → containers Up, localhost/ fails or 502

From the full output you can tell immediately:

- **Containers** → backend-aws or frontend-aws not Up
- **Backend** → /health or /api/health to 127.0.0.1:8002 fails
- **Nginx routing** → direct backend OK but localhost/ or localhost/api/health fails
- **DNS** → check from local machine (nslookup)
- **SSL edge** → localhost OK but external domain fails (browser / curl https)

**If /health and /api/health are OK but the site still fails**, it’s usually one of:

- Nginx proxy path mismatch (e.g. `/api` not forwarded to backend)
- Frontend pointing to wrong API base URL (`NEXT_PUBLIC_API_URL`)
- Mixed-content or CSP blocking scripts
- SSL/cert mismatch at the edge (e.g. cert for wrong host or expired)

Paste the outputs above once and you’ll know whether the problem is containers, backend, nginx routing, DNS, or SSL edge.

---

### One-command fixes

| Situation | Fix |
|-----------|-----|
| **127.0.0.1:8002/api/health OK** but **localhost/api/health fails** | `sudo nginx -t && sudo systemctl restart nginx` |
| **frontend-aws** not Up in `docker compose ps` | `cd ~/crypto-2.0 && docker compose --profile aws up -d frontend-aws` |
| **Backend** not Up | `cd ~/crypto-2.0 && docker compose --profile aws up -d backend-aws` (check logs if it exits) |
| **Both localhost/ and localhost/api/health OK** but **external domain fails** | DNS or SSL at the edge, not the app — fix DNS or cert (e.g. Let’s Encrypt, load balancer) |

---

## C3) 2-minute pinpoint: run A, B, and C (if needed)

Run these tests and paste the outputs. From A + B (and C if external fails) you can tell exactly which of the five states it is and the one fix.

### A) From your laptop

```bash
echo "=== DNS ==="
nslookup dashboard.hilovivo.com

echo ""
echo "=== HTTPS headers ==="
curl -I https://dashboard.hilovivo.com

echo ""
echo "=== External API health ==="
curl -sS https://dashboard.hilovivo.com/api/health
```

**What this tells us:**

- **nslookup doesn’t return your EC2 public IP** → DNS issue.
- **curl -I shows SSL errors or 525/526/520/403** → edge or cert issue.
- **/api/health fails but the site loads** → nginx routing or API base URL.

---

### B) From EC2

```bash
cd ~/crypto-2.0

echo "=== Containers ==="
docker compose --profile aws ps

echo ""
echo "=== Backend direct ==="
curl -sS http://127.0.0.1:8002/health
curl -sS http://127.0.0.1:8002/api/health

echo ""
echo "=== Host nginx local ==="
curl -sS -I http://localhost/ | head -n 10
curl -sS http://localhost/api/health

echo ""
echo "=== Nginx status ==="
sudo systemctl status nginx --no-pager | head -n 30

echo ""
echo "=== Nginx config test ==="
sudo nginx -t
```

**Interpretation (fast):**

- **Backend direct fails** → backend/container issue.
- **Backend direct OK but localhost/api/health fails** → nginx proxy issue.
- **localhost/ fails** → nginx serving frontend issue.
- **Everything on EC2 works but laptop HTTPS fails** → DNS/SSL/edge issue.

---

### C) If EC2 local works but external fails

Do this on EC2 and paste output:

```bash
echo "=== Public IP seen by instance ==="
curl -sS ifconfig.me && echo

echo ""
echo "=== What ports are open locally ==="
sudo ss -lntp | egrep ':(80|443)\s' || true
```

**What this catches:**

- **Nginx is running but Security Group doesn’t allow inbound 80/443** → open 80/443 in the instance Security Group.
- **Nginx isn’t listening on 80/443** → fix nginx config (listen 80; / listen 443 ssl;) and restart.

---

**Paste outputs from A and B (and C if needed).** From that you can tell exactly which of the five it is (containers, backend, nginx routing, DNS, SSL edge) and the one fix.

---

### When DNS is OK but HTTPS fails (SSL_ERROR_SYSCALL)

If you know:

- **DNS is correct** (e.g. `dashboard.hilovivo.com` → your EC2 public IP ✅)
- **HTTPS fails** with e.g. `SSL_ERROR_SYSCALL` ❌

then the domain resolves to EC2 but **nothing valid is speaking HTTPS on port 443**. This is **not** your backend — it’s **edge / nginx / 443** configuration.

---

#### Step 1 — Check if nginx is listening on 443

On EC2:

```bash
sudo ss -lntp | egrep ':(80|443)\s' || true
```

You should see something like:

```
LISTEN 0 511 0.0.0.0:80
LISTEN 0 511 0.0.0.0:443
```

If you **do not** see `:443` → nginx is not listening on HTTPS; that’s the problem.

---

#### Step 2 — Check Security Group

In **AWS Console:** EC2 → Security Groups → select the SG for your instance → **Inbound rules**.

You must have:

| Type | Port | Source    |
|------|------|-----------|
| TCP  | 80   | 0.0.0.0/0 |
| TCP  | 443  | 0.0.0.0/0 |

If **443 is missing** → add it. This is the most common cause of SSL_ERROR_SYSCALL when DNS is correct.

---

#### Step 3 — If 443 is listening but SSL still fails

```bash
sudo nginx -t
sudo systemctl status nginx --no-pager
```

If nginx is running but 443 is misconfigured, likely:

- SSL cert not configured
- Cert path wrong
- Server block missing for 443
- Let’s Encrypt (or cert tool) not installed or not applied

---

#### Quick confirmation test (from your laptop)

```bash
curl -I http://dashboard.hilovivo.com
```

If **HTTP works** but **HTTPS fails** → 100% SSL config issue (SG 443 or nginx HTTPS config).

---

#### Run these on EC2 and paste

```bash
sudo ss -lntp | egrep ':(80|443)\s' || true
sudo nginx -t
```

From that we can fix it immediately (either open 443 in Security Group or fix nginx SSL/server block).

---

### Fork 1: 443 closed or not listening (fix the dashboard)

You’re here when **DNS is correct** and **HTTPS is broken on 443**. The next move is to classify as **Case A, B, or C** using the three commands below.

**Run these and paste outputs.**

**From your laptop:**

```bash
curl -I http://dashboard.hilovivo.com
```

**From EC2:**

```bash
sudo ss -lntp | egrep ':(80|443)\s' || true
sudo nginx -t
```

With those three outputs you’ll know immediately:

| What you see | Case | Action |
|--------------|------|--------|
| **No :443 listener** | A | Run Certbot (see Case A below) |
| **:443 listener** but HTTPS still fails | B | Open SG 443 or fix cert paths, then `nginx -t && systemctl restart nginx` |
| **`nginx -t` fails** | C | Fix the exact config line it prints |

---

**1) From your laptop — check if HTTP responds**

```bash
curl -I http://dashboard.hilovivo.com
```

If **HTTP works** but **HTTPS fails** → 100% 443 or SSL config.

**2) On EC2 — check listeners and nginx config**

```bash
sudo ss -lntp | egrep ':(80|443)\s' || true
sudo nginx -t
```

---

#### The “one fix” depending on what you see

**Case A: No :443 listener**

You need to enable HTTPS in nginx.

**Fast path (Let’s Encrypt):**

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d dashboard.hilovivo.com
sudo systemctl restart nginx
```

Then test from laptop:

```bash
curl -I https://dashboard.hilovivo.com
```

---

**Case B: :443 listener exists but still SSL_ERROR_SYSCALL**

Almost always Security Group or cert path.

- Ensure EC2 **Security Group** → Inbound has **TCP 443** from **0.0.0.0/0** (and **::/0** if you use IPv6).
- Then:

```bash
sudo nginx -t && sudo systemctl restart nginx
```

---

**Case C: `sudo nginx -t` fails**

Paste the error output. It will point to the exact missing file or bad config line (e.g. wrong cert path, syntax error).

---

#### Paste these outputs to know exactly which case

**From EC2:**

- Output of `sudo ss -lntp | egrep ':(80|443)\s' || true`
- Output of `sudo nginx -t`

**From laptop:**

- Output of `curl -I http://dashboard.hilovivo.com`

Once we see those, the fix is a single action (Case A, B, or C).

---

### SSH blocked (80/443 open, 22 closed)

You discover: **port 80 open ✅, port 443 open ✅, port 22 blocked ❌**. The dashboard host is reachable, but **SSH is blocked at the network perimeter**. You can’t fix nginx or the app until you regain access.

**What “dashboard working” means right now:** The host accepts connections on 80/443, but if HTTP gives “Empty reply from server” and HTTPS fails (e.g. SSL_ERROR_SYSCALL), then **no, it’s not working** — and you can’t fix it until you regain access (SSH or SSM).

---

#### Path 1: Fix Security Group SSH (fastest)

In **AWS Console:**

1. **EC2** → **Instances** → select the instance (e.g. public IP 47.130.143.159).
2. **Security** tab → click the **Security Group**.
3. **Inbound rules** → **Edit inbound rules**.
4. **Add rule:**
   - **Type:** SSH  
   - **Port:** 22  
   - **Source:** Your public IP in CIDR, e.g. `YOUR_IP/32`

To get your public IP quickly (from your laptop):

```bash
curl -sS https://ifconfig.me
```

**Temporary emergency option** (use only to recover, then lock down):  
**Source:** `0.0.0.0/0`

5. Save, then retry:

```bash
ssh ubuntu@47.130.143.159
```

If SSH still times out after the SG change, a **NACL** may be blocking 22.

---

#### Path 2: Use AWS SSM Session Manager (no SSH needed)

In **AWS Console:** **EC2** → select instance → **Connect** → **Session Manager**.

If it works, you get a shell and can run the nginx checks immediately.

If it shows **Offline**, it’s usually:

- Instance missing **SSM IAM role** (e.g. `AmazonSSMManagedInstanceCore`).
- No outbound internet/NAT to reach SSM endpoints.

---

#### One question that matters

**Do you have access to the AWS Console right now?**

- **Yes** → Fix Security Group inbound for SSH first (Path 1).
- **No** → Get someone who has access and send them the exact rule to add: **SSH, port 22, Source: your IP/32** (or 0.0.0.0/0 only for emergency recovery).

---

#### DNS points to the wrong IP (instance vs DNS mismatch)

You discover: **instance Public IPv4** (e.g. in EC2 console) is **52.77.216.100**, but **dashboard.hilovivo.com** resolves to **47.130.143.159**. So you’re hitting the **wrong server**.

**What’s happening:**

- Your EC2 instance is running at the **current** public IP (e.g. 52.77.216.100).
- DNS points to a **different** IP (e.g. 47.130.143.159).
- That other IP may be an old instance, a different machine, or a previous Elastic IP — and 22 can be blocked there, 80/443 may not respond properly.

So the dashboard isn’t loading because you’re talking to the wrong machine.

---

**Immediate fix — update DNS**

In **Route 53** (or wherever DNS is hosted):

1. Find the **A** record for **dashboard.hilovivo.com**.
2. Change the value **from** the old IP (e.g. 47.130.143.159) **to** the **current instance Public IPv4** (e.g. 52.77.216.100).
3. Save.

**Then test from your laptop:**

```bash
nslookup dashboard.hilovivo.com
curl -I http://dashboard.hilovivo.com
curl -I https://dashboard.hilovivo.com
```

It should now hit the correct instance.

---

**Long-term fix — use an Elastic IP**

Don’t rely on auto-assigned public IPs (they can change on stop/start or rebuild).

1. In **EC2** → **Elastic IPs** → **Allocate**.
2. **Associate** the Elastic IP with this instance.
3. **Point DNS** to the Elastic IP.

Then the IP never changes on reboot or rebuild. Confirm once you update DNS.

---

#### Once you regain access, run these on EC2 (in this order)

```bash
cd ~/crypto-2.0

sudo systemctl status nginx --no-pager | head -n 60
sudo nginx -t
sudo ss -lntp | egrep ':(80|443)\s' || true

curl -sS -I http://localhost/ | head -n 20
curl -sS http://localhost/api/health
curl -sS http://127.0.0.1:8002/api/health
```

From the outputs you can tell:

- **nginx down** → `systemctl status` shows inactive/failed
- **nginx misconfigured** → `nginx -t` fails
- **missing SSL server block/cert** → no :443 in `ss -lntp` or cert path errors
- **upstream proxy wrong** → localhost/ or localhost/api/health fail but 127.0.0.1:8002/api/health OK
- **backend down** → 127.0.0.1:8002/api/health fails

---

## AWS bring-up commands (quick reference)

- **Full deploy (from repo root on instance):**  
  `cd ~/crypto-2.0 && bash scripts/aws/render_runtime_env.sh && docker compose --profile aws up -d --build`

- **Validate only:**  
  `cd ~/crypto-2.0 && bash scripts/aws/safe_compose_check.sh && docker compose --profile aws config --services`

- **Restart after config change:**  
  `cd ~/crypto-2.0 && docker compose --profile aws up -d --build`

- **Logs (no secrets in command):**  
  `cd ~/crypto-2.0 && docker compose --profile aws logs --tail=200 db backend-aws nginx frontend-aws market-updater-aws 2>/dev/null || docker compose --profile aws logs --tail=200 db backend-aws frontend-aws market-updater-aws`

---

## Troubleshooting

- **"Encrypted Telegram token required" / "decryption failed"**  
  Ensure `secrets/telegram_key` exists and is the same key used to create `TELEGRAM_BOT_TOKEN_ENCRYPTED` (e.g. from `scripts/setup_telegram_token.py`). Ensure `.env.aws` (or SSM) has `TELEGRAM_BOT_TOKEN_ENCRYPTED` and no `TELEGRAM_BOT_TOKEN`.

- **"no service selected"**  
  Always use `--profile aws`: `docker compose --profile aws up -d`, `docker compose --profile aws ps`, etc.

- **backend-aws exits immediately**  
  Check `docker compose --profile aws logs backend-aws`. Common causes: missing `secrets/runtime.env`, missing `secrets/telegram_key`, or invalid encrypted token/key.

- **nginx 502**  
  Restart nginx after backend is healthy: `sudo systemctl restart nginx`. Ensure nginx proxies to `http://127.0.0.1:8002` (or the correct backend address).

---

## D) Critical risk check (do once)

Confirm no plaintext Telegram token exists in the repo or env files. Run on the EC2 instance:

```bash
cd ~/crypto-2.0

# 1) Files that contain the string "TELEGRAM_BOT_TOKEN" followed by "=" (only list file names, never values)
# Linux (GNU grep):
grep -Rl "TELEGRAM_BOT_TOKEN" . 2>/dev/null | xargs grep -l '=' \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=__pycache__ --exclude="*.pyc" || true
# Alternative (any system): git grep -l "TELEGRAM_BOT_TOKEN"

# Must return nothing, OR only files that contain TELEGRAM_BOT_TOKEN_ENCRYPTED= or comments.
# If any file is listed, open it and ensure it has no line assigning a real bot token (plaintext).
# Remove or replace with TELEGRAM_BOT_TOKEN_ENCRYPTED= and rotate the token if it was ever plaintext.
```

Do **not** run `grep -R "123456"` (or real token digits) in a way that prints matching lines—that could leak the token into logs or terminal history. If you need to search for a known prefix, use a script that only reports "found in FILE" without printing the line, or run it in a secure, ephemeral environment.

---

## E) Final security hardening (recommended)

**A) No plaintext token in .env**

- On EC2, `.env` and `.env.aws` must **not** contain a line setting TELEGRAM_BOT_TOKEN to a real value.
- Keep only `TELEGRAM_BOT_TOKEN_ENCRYPTED=...` (and `TELEGRAM_CHAT_ID` etc.). If plaintext was ever present, remove it and rotate the token in BotFather.

**B) Lock key file permissions**

On the instance:

```bash
cd ~/crypto-2.0
chmod 600 secrets/telegram_key
chown ubuntu:ubuntu secrets/telegram_key   # or your app user

# Confirm
ls -la secrets/telegram_key
# Expect: -rw------- 1 ubuntu ubuntu ... secrets/telegram_key
```

---

## F) Operational confidence test (recovery path)

Simulate failure and recovery to prove the stack fails safely and recovers cleanly.

```bash
cd ~/crypto-2.0

# 1) Stop stack
docker compose --profile aws down

# 2) Remove runtime.env (simulate missing secrets)
mv secrets/runtime.env secrets/runtime.env.bak 2>/dev/null || true

# 3) Bring stack up — it should fail clearly (backend/market-updater will fail without runtime.env)
docker compose --profile aws up -d --build
# Expect: backend-aws and/or market-updater-aws may exit or fail health; no plaintext token is used.

# 4) Restore and recover
bash scripts/aws/render_runtime_env.sh
docker compose --profile aws up -d

# 5) Verify
sleep 30
docker compose --profile aws ps
curl -sS http://127.0.0.1:8002/health
# Expect: services Up, health OK. Recovery path validated.
```

---

## G) Next maturity steps

With encrypted Telegram and profile isolation in place you can safely:

- Enable auto-redeploys (e.g. GitHub Actions → SSM run → `render_runtime_env.sh` + `docker compose --profile aws up -d`).
- Add a Prometheus alert on Telegram send failure or health check failure.
- Add a boot-time secret integrity check (e.g. `test -f secrets/telegram_key && test -f secrets/runtime.env` in systemd or deploy script).
- Rotate the Telegram key quarterly: see [Telegram key rotation runbook](TELEGRAM_KEY_ROTATION_RUNBOOK.md).
