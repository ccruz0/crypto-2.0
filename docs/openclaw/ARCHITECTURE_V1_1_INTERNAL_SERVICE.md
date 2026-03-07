# Architecture v1.1 — Internal Service Model (Dashboard ↔ OpenClaw)

## Goal

Serve OpenClaw UI inside the Dashboard without exposing OpenClaw to the public internet.

## Target state

- OpenClaw reachable only over VPC private networking.
- Dashboard proxies `/openclaw/` to OpenClaw over private IP.
- Access controlled with Nginx Basic Auth on the Dashboard.

## Components

- **Dashboard EC2**
  - Public: `dashboard.hilovivo.com` (Nginx 443)
  - Private: `172.31.x.x`
- **OpenClaw EC2**
  - Private only: `172.31.y.y`
  - Service: `http://172.31.y.y:8080/`
  - No public inbound on 8080

## Data flow

```
Client browser
→ https://dashboard.hilovivo.com/openclaw/
→ Nginx (Dashboard)
→ http://<OPENCLAW_PRIVATE_IP>:8080/
→ OpenClaw service
```

## Nginx contract (Dashboard)

Inside the `server { listen 443 ssl; server_name dashboard.hilovivo.com; }` block:

- **Redirect**
  - `location = /openclaw { return 301 /openclaw/; }`
- **Proxy** (must be before `location / { proxy_pass http://127.0.0.1:3000; }`)
  - `location ^~ /openclaw/ { ... proxy_pass http://<OPENCLAW_PRIVATE_IP>:8080/; ... }`
- **Headers** for embedding + auth correctness
  - CSP: `frame-ancestors 'self' https://dashboard.hilovivo.com` with `always`
  - Clear XFO with `always` (avoid iframe blocks on 401)
- **Auth**
  - `auth_basic "OpenClaw";`
  - `auth_basic_user_file /etc/nginx/.htpasswd_openclaw;`

## Security model

### Security Groups

**OpenClaw SG inbound:**

- TCP 8080
- Source: Dashboard SG (SG-to-SG reference)

**Dashboard SG inbound:**

- TCP 443 from 0.0.0.0/0 (public web)
- SSH restricted as per ops policy

### Public exposure policy

- OpenClaw must **NOT** have inbound TCP 8080 from 0.0.0.0/0 in steady state.
- Prefer no public IPv4 on OpenClaw (optional but recommended).

## Health and failure modes

**Expected external behavior:**

- `curl -I https://dashboard.hilovivo.com/openclaw/` → 401
- Browser: Basic Auth prompt then OpenClaw UI loads

**Failure modes:**

| Symptom | Cause |
|--------|--------|
| 504 | Dashboard cannot reach OpenClaw private IP:8080. Runbook: validate 3 invariants; paste 3 outputs → 1 change. |
| 404 | Missing OpenClaw locations in server 443 → request falls to frontend |
| Blank iframe | Auth/headers/401 behavior (use iframe diagnosis runbook) |

## Operational runbooks

- **Migration:** [OPENCLAW_PRIVATE_NETWORK_MIGRATION.md](OPENCLAW_PRIVATE_NETWORK_MIGRATION.md)
- **504 upstream timeout:** [OPENCLAW_504_UPSTREAM_DIAGNOSIS.md](OPENCLAW_504_UPSTREAM_DIAGNOSIS.md) — deterministic (Nginx → curl → bind); don’t interpret, just paste.
- **308/404 routing:** [FIX_OPENCLAW_308_REDIRECT.md](FIX_OPENCLAW_308_REDIRECT.md)
- **Blank iframe:** [OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md](OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md)

## Guardrails (non-negotiables)

- Do **not** proxy OpenClaw via public IP in steady state.
- Do **not** open OpenClaw:8080 to the internet.
- Proxy block must exist in **server 443** and be ordered **before** `location /`.
- Any backup files must **not** live under `sites-enabled/`.

## Optional next step (v1.2)

Internal ALB in front of OpenClaw:

- Health checks
- Cleaner service discovery
- Scaling path
