# Deploy real OpenClaw application on LAB (replace placeholder)

**Goal:** Run the real OpenClaw application instead of the placeholder container that shows "Placeholder. Replace OPENCLAW_IMAGE with full app when ready."

**Current situation:** OpenClaw endpoint works (https://dashboard.hilovivo.com/openclaw/), nginx proxy works, container on LAB responds on 8080, but the UI is the placeholder.

**Infrastructure:**
- **PROD:** atp-rebuild-2026, nginx, dashboard.hilovivo.com
- **LAB:** atp-lab-ssm-clean, private IP 172.31.3.214, port 8080, `docker-compose.openclaw.yml` present

---

## 1. Image reference

| Image | Description |
|-------|-------------|
| **Placeholder** (current) | `ghcr.io/ccruz0/crypto-2.0:openclaw` — built by this repo's workflow from `openclaw/Dockerfile` (minimal HTML). |
| **Real app** | `ghcr.io/ccruz0/openclaw:latest` — built from the OpenClaw application repo and pushed to GHCR. |

To use the real app, LAB must set **`OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest`** in `.env.lab`. If that image is not yet built/pushed, build and push it from the OpenClaw application source repo first (see docs/openclaw/BUILD_AND_PUSH_OPENCLAW_IMAGE.md).

---

## 2. Connect to LAB

You **cannot** SSH from your Mac to `172.31.3.214` (private IP). Use **AWS SSM**:

```bash
aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
```

Or from **PROD** you can SSH to LAB only if key and security groups allow it; otherwise use SSM from Mac.

---

## 3. On LAB: check current container and compose

```bash
docker ps
cat /home/ubuntu/crypto-2.0/docker-compose.openclaw.yml
cat /home/ubuntu/crypto-2.0/.env.lab | grep -E "OPENCLAW_IMAGE|GIT_REPO"
```

Note the current `OPENCLAW_IMAGE` (likely `ghcr.io/ccruz0/crypto-2.0:openclaw` or unset → placeholder).

---

## 4. On LAB: set real image and restart

**Option A — Script (after `git pull origin main`):**

```bash
cd /home/ubuntu/crypto-2.0
git pull origin main
bash scripts/openclaw/deploy_real_openclaw_on_lab.sh
```

**Option B — Manual:**

```bash
cd /home/ubuntu/crypto-2.0
git pull origin main

# Set real OpenClaw image (create .env.lab from example if missing)
export OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest
grep -q '^OPENCLAW_IMAGE=' .env.lab 2>/dev/null \
  && sed -i "s|^OPENCLAW_IMAGE=.*|OPENCLAW_IMAGE=$OPENCLAW_IMAGE|" .env.lab \
  || echo "OPENCLAW_IMAGE=$OPENCLAW_IMAGE" >> .env.lab

# Restart with new image
docker compose -f docker-compose.openclaw.yml down
docker compose -f docker-compose.openclaw.yml pull
docker compose -f docker-compose.openclaw.yml up -d
```

If `pull` fails with "image not found", the real image is not yet in GHCR — build and push it from the OpenClaw application repo (see § "If the real image does not exist yet"), or use a different tag if you publish elsewhere.

---

## 5. Verify on LAB

```bash
curl -sS -m 5 http://localhost:8080/ | head -20
docker compose -f docker-compose.openclaw.yml ps
```

You should see the real OpenClaw UI (not the placeholder HTML).

---

## 6. Verify from anywhere

```bash
curl -sI https://dashboard.hilovivo.com/openclaw/
```

Expect **401** (Basic Auth). Then open in browser: https://dashboard.hilovivo.com/openclaw/ — log in and confirm the real app loads.

---

## One-liner (on LAB, after SSM connect)

```bash
cd /home/ubuntu/crypto-2.0 && \
export OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest && \
(grep -q '^OPENCLAW_IMAGE=' .env.lab && sed -i "s|^OPENCLAW_IMAGE=.*|OPENCLAW_IMAGE=$OPENCLAW_IMAGE|" .env.lab || echo "OPENCLAW_IMAGE=$OPENCLAW_IMAGE" >> .env.lab) && \
docker compose -f docker-compose.openclaw.yml down && \
docker compose -f docker-compose.openclaw.yml pull && \
docker compose -f docker-compose.openclaw.yml up -d && \
sleep 3 && curl -sS -m 5 http://localhost:8080/ | head -5
```

---

## If the real image does not exist yet

1. Get the OpenClaw **application** source repo (the one that builds the full UI, not this ATP repo).
2. Build and push to GHCR, e.g.:
   ```bash
   docker build -t ghcr.io/ccruz0/openclaw:latest .
   docker push ghcr.io/ccruz0/openclaw:latest
   ```
3. Then run the steps above on LAB.

See **docs/openclaw/BUILD_AND_PUSH_OPENCLAW_IMAGE.md** for details.
