# OpenClaw — Continue installation (LAB)

Use this when **apt is already working** on LAB (e.g. after switching to HTTPS) and you want to get OpenClaw running. Instance: **i-0d82c172235770a0d** (atp-lab-ssm-clean, ap-southeast-1).

---

## One command on LAB (do it all)

In an SSM session to LAB, run **one** of these:

**Option A — Fetch and run (script must be on `main`):**
```bash
bash <(curl -sSL https://raw.githubusercontent.com/ccruz0/crypto-2.0/main/scripts/openclaw/install_on_lab.sh)
```
When prompted, paste your GitHub fine-grained PAT (Contents R/W, Pull requests R/W, Metadata R).

**Option B — Clone then run (use this if Option A 404s before you push):**
```bash
sudo apt update
git clone https://github.com/ccruz0/crypto-2.0.git /home/ubuntu/crypto-2.0
cd /home/ubuntu/crypto-2.0 && bash scripts/openclaw/install_on_lab.sh
```
If `apt update` fails with "Network is unreachable", run the [apt-over-HTTPS](#on-the-lab-instance-via-ssm--run-in-order) block first.

The script: switches apt to HTTPS, installs Docker + git, clones repo (if needed), prompts for token, creates `.env.lab`, starts OpenClaw, and enables the systemd service.

---

## From your Mac (optional)

Check LAB is ready and print command blocks for SSM:

```bash
./scripts/aws/openclaw_lab_preflight.sh
```

Then start an SSM session:

```bash
aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
```

---

## On the LAB instance (via SSM) — run in order

### Step 1 — Prepare host (Docker, repo)

Paste this block in the SSM terminal:

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 2>/dev/null || true
sudo usermod -aG docker "$(whoami)"
cd /home/ubuntu
[ -d automated-trading-platform ] || git clone https://github.com/ccruz0/crypto-2.0.git automated-trading-platform
cd automated-trading-platform
git fetch origin main && git checkout main
```

If `docker` later says "permission denied", start a **new** SSM session (so group `docker` is picked up), or run: `newgrp docker`.

---

### Step 2 — GitHub token (Phase 1)

You need a **fine-grained PAT**: Contents (R/W), Pull requests (R/W), Metadata (R).

```bash
mkdir -p ~/secrets
chmod 700 ~/secrets
touch ~/secrets/openclaw_token
chmod 600 ~/secrets/openclaw_token
read -r -s -p 'Paste GitHub fine-grained PAT: ' TOKEN
echo -n "$TOKEN" > ~/secrets/openclaw_token
unset TOKEN
test -r ~/secrets/openclaw_token && echo "OK: token readable"
```

---

### Step 3 — .env.lab

```bash
cd /home/ubuntu/crypto-2.0
cp .env.lab.example .env.lab
chmod 600 .env.lab
```

Edit `.env.lab` (e.g. `nano .env.lab`) and set at least:

- `GIT_REPO_URL=https://github.com/ccruz0/crypto-2.0.git`
- `OPENCLAW_TOKEN_PATH=/home/ubuntu/secrets/openclaw_token`
- `OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest`  
  (If that image does not exist yet, you must build and push an OpenClaw image to GHCR or use a local build; see [DEPLOYMENT.md](DEPLOYMENT.md).)

Do **not** put the token value in `.env.lab`. Check:

```bash
grep -i token .env.lab
# Should show only OPENCLAW_TOKEN_PATH=...
```

---

### Step 4 — Start OpenClaw

```bash
cd /home/ubuntu/crypto-2.0
docker compose -f docker-compose.openclaw.yml up -d
docker compose -f docker-compose.openclaw.yml ps
docker compose -f docker-compose.openclaw.yml logs -f openclaw
```

If you see "image not found", set a valid `OPENCLAW_IMAGE` in `.env.lab` (image in GHCR or built locally).

---

### Step 5 (optional) — Start on reboot

```bash
sudo cp /home/ubuntu/crypto-2.0/scripts/openclaw/openclaw.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openclaw
sudo systemctl start openclaw
```

---

## After installation

1. **Confirm container:** On LAB, `docker compose -f docker-compose.openclaw.yml ps` and `logs -f openclaw`.
2. **Phase 2 validation:** [LAB_SETUP_AND_VALIDATION.md](LAB_SETUP_AND_VALIDATION.md) — push to `openclaw/*`, create PR via API, confirm "add label" returns 403.
3. **Security:** [FINAL_SECURITY_CHECKLIST.md](FINAL_SECURITY_CHECKLIST.md).

Full runbook: [RUNBOOK_OPENCLAW_LAB.md](RUNBOOK_OPENCLAW_LAB.md).
