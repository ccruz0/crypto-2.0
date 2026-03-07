# Open OpenClaw and run audit — do this now

**Canonical (no ambiguity):**
- **PROD:** atp-rebuild-2026 — private **172.31.32.169** — serves dashboard.hilovivo.com (nginx + docker profile aws).
- **LAB:** atp-lab-ssm-clean — private **172.31.3.214** — OpenClaw only.
- **atp-lab-openclaw:** keep stopped.

**Critical corrections (apply in all audits):**
1. **LAB** = atp-lab-ssm-clean (the one running for OpenClaw). atp-lab-openclaw is a separate instance (stopped).
2. **OpenAPI is not available in PROD.** Do not rely on OpenAPI for audits — use live routes and responses.

---

## Step 1: Confirm which instance is LAB and which is PROD

In AWS Console:
- **PROD** = instance serving dashboard.hilovivo.com (nginx + docker profile aws).
- **LAB** = instance meant to run OpenClaw only.

**Fast verification from each instance (via Instance Connect):**

On each instance run:

```bash
hostname
curl -sI https://dashboard.hilovivo.com/openclaw/ | head -n 5
sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

You’ll see:
- **PROD:** nginx + frontend/backend containers.
- **LAB:** openclaw container on 8080 (or a service).

---

## Step 2: Get OpenClaw running on LAB

On the **LAB** instance:

```bash
cd /home/ubuntu/automated-trading-platform
ls -la docker-compose.openclaw.yml scripts/openclaw || true

sudo docker compose -f docker-compose.openclaw.yml up -d
sudo docker compose -f docker-compose.openclaw.yml ps
ss -tlnp | grep -E "8080|18789" || true
curl -sI http://127.0.0.1:8080/ | head -n 5
```

If `docker-compose.openclaw.yml` is not found:

```bash
cd /home/ubuntu/automated-trading-platform
find . -maxdepth 3 -iname "*openclaw*compose*" -o -iname "*openclaw*.yml"
```

---

## Step 3: Make PROD nginx proxy to LAB (use private IP)

Use **LAB private IP** in nginx when both are in the same VPC.

**On LAB:** get private IP

```bash
hostname -I
```

Pick the **172.*** private IP (e.g. `172.31.3.214`).

**On PROD:** point nginx to LAB private IP **172.31.3.214**

One-liner (on PROD):

```bash
cd /home/ubuntu/automated-trading-platform && sudo bash scripts/openclaw/point_prod_nginx_to_lab_private_ip.sh
```

Or manually: find the site config, set `proxy_pass http://172.31.3.214:8080/;`, then:

```bash
sudo nginx -t
sudo systemctl reload nginx
curl -sI https://dashboard.hilovivo.com/openclaw/ | head -n 20
```

---

## Step 4: Security groups — PROD → LAB on 8080

**Done.** LAB SG **atp-lab-sg2** (sg-021aefb689b9d3c0e) has inbound TCP 8080 from PROD SG **launch-wizard-6** (sg-07f5b0221b7e69efe). No public inbound.

To verify: AWS Console → EC2 → Security Groups → atp-lab-sg2 → Inbound rules → TCP 8080 from sg-07f5b0221b7e69efe.

---

## Step 5: Give OpenClaw the audit mission

Once https://dashboard.hilovivo.com/openclaw/ loads, paste this prompt into OpenClaw (English):

```
Mission: Audit ATP production vs documentation and find inconsistencies causing "trigger orders not visible".

Rules:
- Prefer facts from the running PROD instance over docs.
- Produce minimal diffs only. Do not refactor.
- No secrets in logs or output.

Work plan:
1) On PROD:
   - Capture nginx routing for /, /api, /openclaw (extract from nginx -T).
   - List FastAPI routes from inside backend container (print routes containing 'orders').
   - Call the live endpoints used by the frontend Orders tab and record JSON shape.
2) Read docs:
   - docs/runbooks/**, docs/aws/**, docs/openclaw/**, DEPLOY*.md.
3) Deliver:
   A) Findings
   B) Root cause ranked
   C) Minimal patch (file + diff snippets)
   D) Verification checklist commands

Start by proving which endpoint the frontend calls for Orders and whether it includes trigger orders.
```

**One thing to do now:** After the nginx change on PROD, run `curl -I https://dashboard.hilovivo.com/openclaw/` and paste the headers (+ any 502/404) to confirm the proxy is correct or if LAB isn’t listening on 8080 yet.

---

**Reference:** [README.md](README.md), [ARCHITECTURE_V1_1_INTERNAL_SERVICE.md](ARCHITECTURE_V1_1_INTERNAL_SERVICE.md).
