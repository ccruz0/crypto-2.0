# OpenClaw Lab Setup and Validation Commands

**Target:** AWS Lab instance (Ubuntu, t3.small). Do not run on production.

---

## Phase 1 – Secure Token Handling (Lab Setup)

Run on the **Lab EC2** instance (e.g. via SSM Session Manager or SSH).

### 1.1 Create secrets directory and token file

```bash
# Create secrets directory (700)
mkdir -p ~/secrets
chmod 700 ~/secrets

# Create token file (do NOT commit this file or its path with content)
# Paste your fine-grained PAT when prompted; or use a here-doc without logging
touch ~/secrets/openclaw_token
chmod 600 ~/secrets/openclaw_token
chown "$(whoami):$(whoami)" ~/secrets/openclaw_token

# Write token (paste token when prompted; it will not echo)
read -r -s -p 'Paste GitHub fine-grained PAT: ' TOKEN
echo -n "$TOKEN" > ~/secrets/openclaw_token
unset TOKEN

# Verify permissions
ls -la ~/secrets/
ls -la ~/secrets/openclaw_token
# Expected: drwx------ secrets; -rw------- openclaw_token
```

### 1.2 Ensure token is NOT in repository or .env

```bash
# From repo root (e.g. ~/automated-trading-platform)
cd ~/automated-trading-platform  # or your clone path

# .env.lab must NOT contain the token (only OPENCLAW_TOKEN_PATH and other non-secrets)
cp .env.lab.example .env.lab
chmod 600 .env.lab

# Edit .env.lab: set GIT_REPO_URL, OPENCLAW_TOKEN_PATH=/home/ubuntu/secrets/openclaw_token, OPENCLAW_IMAGE if needed
# Do NOT add OPENCLAW_GITHUB_TOKEN or any token value to .env.lab
nano .env.lab

# Sanity: token must not appear in .env.lab
grep -i token .env.lab
# Should show only OPENCLAW_TOKEN_PATH=... (path, not the secret value)
```

### 1.3 Verify Docker will mount token read-only

```bash
# Token path must exist and be readable by ubuntu user
test -r ~/secrets/openclaw_token && echo "OK: token file readable" || echo "FAIL: token file missing or not readable"
```

---

## Phase 2 – Git Integration (HTTPS + Token Auth)

Run from the Lab instance. Assumes `git` and `curl` (or `jq`) are installed.

### 2.1 Configure Git remote to HTTPS

```bash
cd ~/automated-trading-platform  # or your clone path
git remote -v
# Should show: origin  https://github.com/ccruz0/crypto-2.0.git (fetch) (push)
# If SSH (git@github.com:...), switch to HTTPS:
git remote set-url origin https://github.com/ccruz0/crypto-2.0.git
git remote -v
```

### 2.2 Configure Git to use token for HTTPS (for this repo only)

Token is stored in `~/secrets/openclaw_token`. Use a credential helper that reads from that file so the token is never stored in `git config` or `.env`.

**Security:** The helper outputs the token to **stdout** (for Git only). Do not run it in a context where stdout is logged or captured. Do **not** use `credential.helper store` (writes plaintext to ~/.git-credentials).

```bash
# Create a credential helper script (outside repo; do not commit)
mkdir -p ~/bin
cat > ~/bin/git-credential-openclaw << 'HELPER'
#!/bin/sh
# Output Git credential (username + password) from token file. Used for HTTPS push.
# Only Git should read this stdout; do not log or capture.
printf "username=ccruz0\npassword=%s\n" "$(cat ~/secrets/openclaw_token)"
HELPER
chmod 700 ~/bin/git-credential-openclaw

# Use it for this repo only (fill = provide password when Git asks)
git config --local credential.helper '!/home/ubuntu/bin/git-credential-openclaw'
# Or if ~/bin is in PATH:
git config --local credential.helper '!git-credential-openclaw'
```

For **push over HTTPS**: when you run `git push`, Git will invoke the helper and get the token from the file; the token is not written to disk elsewhere. Do **not** use `credential.helper store` (it writes plaintext to ~/.git-credentials).

### 2.3 Validation test commands (Git + API)

Run these to verify permissions. Replace `REPO_OWNER`, `REPO_NAME`, and branch names as needed.

**Warning:** These commands load the token into the shell (e.g. `TOKEN=$(cat ...)`). Run only in a **manual** session; do not run from scripts that log commands or stdout, and run `unset TOKEN` when done.

```bash
# Set vars (do not commit; do not log)
REPO_OWNER=ccruz0
REPO_NAME=crypto-2.0
TOKEN=$(cat ~/secrets/openclaw_token)

# --- 1) Create branch (via Git + push) ---
cd ~/automated-trading-platform
git fetch origin main
git checkout -b openclaw/validation-$(date +%Y%m%d-%H%M%S) origin/main
# Make a trivial change so we can push
echo "# OpenClaw validation $(date -Iseconds)" >> docs/openclaw/VALIDATION_LOG.md
git add docs/openclaw/VALIDATION_LOG.md
git commit -m "chore(openclaw): validation branch"
git push -u origin "$(git branch --show-current)"
# Expected: push succeeds (Contents: Read & Write)

# --- 2) Open PR via API (expect 201) ---
BRANCH=$(git branch --show-current)
PR_JSON=$(curl -s -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $TOKEN" \
  "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/pulls" \
  -d "{\"title\":\"OpenClaw validation PR\",\"head\":\"${BRANCH}\",\"base\":\"main\"}")
echo "$PR_JSON" | head -20
# Expected: "number": <n>, "state": "open"
PR_NUM=$(echo "$PR_JSON" | sed -n 's/.*"number": *\([0-9]*\).*/\1/p')
echo "PR number: $PR_NUM"

# --- 3) Apply label via API (expect 403 – no Issues/Labels permission) ---
LABEL_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $TOKEN" \
  "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/issues/${PR_NUM}/labels" \
  -d '["documentation"]')
HTTP_CODE=$(echo "$LABEL_RESPONSE" | tail -n1)
echo "Apply label HTTP code: $HTTP_CODE"
# Expected: 403 (Forbidden) – token has no Issues/Labels permission
if [ "$HTTP_CODE" = "403" ]; then
  echo "PASS: Label application correctly denied (403)"
else
  echo "CHECK: Expected 403 for label; got $HTTP_CODE"
fi

# Cleanup: close the test PR (optional; requires PATCH on pull request)
# curl -s -X PATCH -H "Authorization: Bearer $TOKEN" \
#   "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/pulls/${PR_NUM}" \
#   -d '{"state":"closed"}'
unset TOKEN
```

### 2.4 One-liner validation summary

```bash
# Quick checks (token in env for this session only – do not log)
export TOKEN=$(cat ~/secrets/openclaw_token)
# Can create branch + push
git -C ~/automated-trading-platform fetch origin main && git -C ~/automated-trading-platform checkout -b openclaw/test-$(date +%s) origin/main && touch /tmp/tt && git -C ~/automated-trading-platform add -A && git -C ~/automated-trading-platform commit -m "validation" --allow-empty && git -C ~/automated-trading-platform push -u origin HEAD && echo "PUSH OK"
# Open PR (expect 201)
curl -s -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" "https://api.github.com/repos/ccruz0/crypto-2.0/pulls" -d '{"title":"v","head":"openclaw/test-'$(date +%s)'","base":"main"}'
# Apply label (expect 403) – use a real PR number if you have one
curl -s -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" "https://api.github.com/repos/ccruz0/crypto-2.0/issues/1/labels" -d '["documentation"]'
unset TOKEN
```

---

## Phase 3 – Start Hardened OpenClaw Service

```bash
cd ~/automated-trading-platform
docker compose -f docker-compose.openclaw.yml up -d
docker compose -f docker-compose.openclaw.yml ps
docker compose -f docker-compose.openclaw.yml logs --tail 50 openclaw
```

### Install systemd (persist across reboot)

```bash
sudo cp ~/automated-trading-platform/scripts/openclaw/openclaw.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openclaw
sudo systemctl start openclaw
sudo systemctl status openclaw
```

### Verify container hardening

```bash
# Non-root
docker exec openclaw id
# Expected: uid=1000 gid=1000

# Read-only root
docker exec openclaw sh -c 'touch /x 2>&1'
# Expected: Read-only file system (or similar)

# Token present as file, not in env
docker exec openclaw env | grep -i token
# Expected: OPENCLAW_TOKEN_FILE=/run/secrets/openclaw_token (path only; no token value)
docker exec openclaw cat /run/secrets/openclaw_token | head -c 4
# Expected: first 4 chars of token (do not log full output)

# No docker socket
docker exec openclaw ls /var/run/docker.sock 2>&1
# Expected: No such file or directory
```

---

## Phase 4 – Cost Optimization (Reference)

- **Instance:** t3.small (2 vCPU, 4 GiB); container limits 2 GB RAM, 1 CPU.
- **No autoscaling;** local logging with rotation; no verbose CloudWatch.
- **Estimated monthly cost:** ~20–35 USD (see docs/openclaw/COST_MODEL.md).

---

## Phase 5 – Security Validation

Use **docs/openclaw/FINAL_SECURITY_CHECKLIST.md** and run the API permission tests above. Ensure:

- Token scope: Contents R/W, Pull requests R/W, Metadata read; no Issues, no admin.
- Label protection: Applying label via API returns 403.
- Branch protection: main is protected (required checks, PR required); do not modify from Lab.
- Path-guard: Required check on main; PRs touching protected paths need `security-approved`.
- Secrets: Token only in ~/secrets/openclaw_token; not in repo or .env.lab.
- Docker: Non-root, read_only, cap_drop ALL, no docker socket, token mounted ro.
