# GitHub App Creation and Cutover Runbook

**Repository:** `ccruz0/crypto-2.0` (personal account `ccruz0`)  
**Region:** `ap-southeast-1` (default in scripts)  
**EC2 instance:** `i-087953603011543c5` (atp-rebuild-2026)

> **WARNING — PAT deletion gate:** Do **not** delete `/automated-trading-platform/prod/github_token`
> until `auth_mode: github_app` has been **stable for 24–48 hours** (no auth errors in logs,
> deploy dispatch and Cursor bridge smokes passed). The PAT is the only rollback path.

**Helper scripts (this repo):**

| Script | Purpose |
|--------|---------|
| `scripts/aws/setup_github_app_ssm_template.sh` | Operator-run SSM writer (validated, dry-run capable, never echoes the key) |
| `scripts/aws/render_and_recreate_backend_safe.sh` | Render runtime.env + recreate backend-aws + health wait + verify |
| `scripts/aws/verify_github_app_cutover_ready.sh` | One-shot readiness check; prints `CUTOVER_READY=YES/NO` |

---

## Prerequisites

- GitHub organization or user account with permission to create GitHub Apps
- AWS CLI configured with `ssm:PutParameter` and `ssm:GetParameter` on prod paths
- SSH or SSM access to PROD EC2
- PR #32 merged and deployed (or deploy immediately after this runbook's SSM step)

---

## 1. Create the GitHub App

1. Open: **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
   - Direct URL: `https://github.com/settings/apps/new`

2. **GitHub App name:** `ATP Production Automation` (or your naming convention)

3. **Homepage URL:** `https://dashboard.hilovivo.com`

4. **Webhook:** Uncheck **Active** (not required for installation-token API calls unless you add webhook handlers later)

5. **Permissions** (minimum for deploy trigger, Cursor bridge PRs, workflow dispatch):

   | Permission | Access |
   |------------|--------|
   | **Actions** | Read and write |
   | **Contents** | Read and write |
   | **Pull requests** | Read and write |
   | **Metadata** | Read-only (automatic) |

6. **Subscribe to events:** None required for token-based API use

7. **Where can this GitHub App be installed?** Only on this account (recommended) or any account (if org-wide)

8. Click **Create GitHub App**

---

## 2. Generate and download the private key (PEM)

1. On the App settings page: **Private keys → Generate a private key**
2. Save the downloaded file locally, e.g.:

   ```bash
   # On your operator machine
   mkdir -p ~/atp-secrets/github-app
   mv ~/Downloads/*.pem ~/atp-secrets/github-app/atp-prod-private-key.pem
   chmod 600 ~/atp-secrets/github-app/atp-prod-private-key.pem
   ```

---

## 3. Install the App on the repository

1. App settings → **Install App**
2. Select account/org → **Only select repositories**
3. Choose: `ccruz0/crypto-2.0`
4. Click **Install**

---

## 4. Obtain App ID

**From the UI:**

1. GitHub → Settings → Developer settings → GitHub Apps → your app
2. Copy **App ID** (numeric, e.g. `123456`)

**From CLI (requires `gh` auth):**

```bash
gh api /apps/atp-production-automation --jq .id
# Replace slug with your app slug (lowercase, hyphens)
```

Record as `YOUR_APP_ID`.

---

## 5. Obtain Installation ID

**From the UI:**

1. App → **Install App** → click the gear ⚙️ next to the installation
2. URL format: `https://github.com/settings/installations/INSTALLATION_ID`
3. Copy the numeric `INSTALLATION_ID` from the URL

**From CLI:**

```bash
gh api /repos/ccruz0/crypto-2.0/installation --jq .id
```

Record as `YOUR_INSTALLATION_ID`.

---

## 6. Base64-encode the PEM to a file (single line)

The setup script reads the encoded key from a **file** (`GITHUB_APP_PRIVATE_KEY_B64_FILE`) so the
key never appears in shell history or environment listings.

**Linux:**

```bash
base64 -w0 ~/atp-secrets/github-app/atp-prod-private-key.pem > ~/atp-secrets/github-app/github_app_private_key.b64
chmod 600 ~/atp-secrets/github-app/github_app_private_key.b64
```

**macOS:**

```bash
base64 -i ~/atp-secrets/github-app/atp-prod-private-key.pem | tr -d '\n' > ~/atp-secrets/github-app/github_app_private_key.b64
chmod 600 ~/atp-secrets/github-app/github_app_private_key.b64
```

**Verify PEM shape (no secret printed):**

```bash
base64 -d < ~/atp-secrets/github-app/github_app_private_key.b64 | head -1
# Expected: -----BEGIN RSA PRIVATE KEY-----  OR  -----BEGIN PRIVATE KEY-----
```

---

## 7. Store parameters in AWS SSM (use the setup script)

Use `scripts/aws/setup_github_app_ssm_template.sh`. It validates inputs (numeric IDs,
non-empty key file, PEM decode check), writes the three parameters, never echoes the key,
and prints only names/types/versions.

**Dry run first (nothing written, secrets masked):**

```bash
cd /home/ubuntu/crypto-2.0   # or your operator checkout
DRY_RUN=1 \
GITHUB_APP_ID_VALUE="123456" \
GITHUB_APP_INSTALLATION_ID_VALUE="78901234" \
GITHUB_APP_PRIVATE_KEY_B64_FILE=~/atp-secrets/github-app/github_app_private_key.b64 \
bash scripts/aws/setup_github_app_ssm_template.sh
```

**Real write:**

```bash
GITHUB_APP_ID_VALUE="123456" \
GITHUB_APP_INSTALLATION_ID_VALUE="78901234" \
GITHUB_APP_PRIVATE_KEY_B64_FILE=~/atp-secrets/github-app/github_app_private_key.b64 \
bash scripts/aws/setup_github_app_ssm_template.sh
```

Parameters written:

| Name | Type |
|------|------|
| `/automated-trading-platform/prod/github_app/app_id` | String |
| `/automated-trading-platform/prod/github_app/installation_id` | String |
| `/automated-trading-platform/prod/github_app/private_key_b64` | SecureString |

The script prints a presence table (names/types/versions only) after writing.

---

## 8. Runtime rendering on EC2 (use the safe helper)

> **WARNING — LAB fallback:** `render_runtime_env.sh` falls back to the LAB SSM path
> (`/automated-trading-platform/lab/github_app/*`) when the PROD `github_app/*` parameters
> are absent. **Verify the LAB `github_app/*` params are empty before rendering** so stale
> LAB credentials cannot silently flip `auth_mode` to `github_app` on PROD:
>
> ```bash
> aws ssm describe-parameters \
>   --region ap-southeast-1 \
>   --parameter-filters "Key=Name,Option=BeginsWith,Values=/automated-trading-platform/lab/github_app/" \
>   --query 'Parameters[].Name' --output table
> # Expected before cutover: empty
> ```

SSH to PROD:

```bash
ssh ubuntu@dashboard.hilovivo.com
cd /home/ubuntu/crypto-2.0
git pull --ff-only origin main
```

Run the safe render + recreate helper (renders from SSM, fixes runtime.env ownership,
recreates backend-aws, waits up to 120s for health, runs the verify script):

```bash
bash scripts/aws/render_and_recreate_backend_safe.sh
```

After the cutover render, also recreate the canary so its env stays in parity with
`backend-aws` (the safe helper only recreates `backend-aws`):

```bash
docker compose --profile aws up -d --force-recreate backend-aws-canary
```

**Expected render summary line within output:**

```
GITHUB_APP=YES GITHUB_AUTH_MODE=github_app ALLOW_LEGACY_GITHUB_PAT=NO
```

**Expected final line:**

```
auth_mode: github_app
```

---

## 9. Validation

### 9a. Host file check (no values)

```bash
grep -E '^(GITHUB_APP_ID|GITHUB_APP_INSTALLATION_ID|GITHUB_APP_PRIVATE_KEY_B64|ALLOW_LEGACY_GITHUB_PAT|GITHUB_AUTH_MODE)=' secrets/runtime.env \
  | sed 's/=.*/=<set>/'
```

**Expected:**

- `GITHUB_APP_ID=<set>`
- `GITHUB_APP_INSTALLATION_ID=<set>`
- `GITHUB_APP_PRIVATE_KEY_B64=<set>`
- `ALLOW_LEGACY_GITHUB_PAT` — **absent** or empty
- `GITHUB_AUTH_MODE` — **absent** (not written to file; render prints to stdout only)

### 9b. Container check

```bash
./scripts/verify_deploy_secrets.sh
```

**Expected:**

```
GitHub App ready (all three): yes
ALLOW_LEGACY_GITHUB_PAT: no
auth_mode: github_app
Deploy automation ready? YES
```

### 9b-bis. One-shot readiness check

```bash
bash scripts/aws/verify_github_app_cutover_ready.sh
```

> **Do not trust presence-only checks.** `CUTOVER_READY=YES` requires a **live in-container
> token mint** (`get_github_api_token()` returning `auth_method=github_app` with a token
> present), not merely the presence of `GITHUB_APP_*` env vars. Vars can be present yet
> invalid (wrong App ID, bad PEM, wrong installation ID); only a successful mint proves
> the App path works. If vars are present but the mint fails, the script prints
> `NO-GO: GitHub App vars present but live token mint failed.` and `CUTOVER_READY=NO`.

**Expected after cutover:** `CUTOVER_READY=YES`

**While still in transition (App SSM params absent):**

```
Transition mode active. Safe, but GitHub App cutover not complete.
CUTOVER_READY=NO
```

### 9c. Startup logs

```bash
docker compose --profile aws logs backend-aws --tail=100 | grep -E 'GitHub auth|auth_method|Deploy secrets'
```

With `ATP_TRADING_ONLY=1`, startup GitHub checks are skipped — rely on verify script and smoke tests.

### 9d. In-container auth smoke (no token printed)

```bash
docker compose --profile aws exec backend-aws python3 - <<'PY'
from app.services.github_app_auth import get_github_api_token
token, method = get_github_api_token()
print("auth_method:", method)
print("token_present:", bool(token))
PY
```

**Expected:** `auth_method: github_app`, `token_present: True`

---

## 10. Smoke testing

Run with `ATP_TRADING_ONLY=1` first (production safe). Tests exercise runtime paths without enabling full automation startup gates.

### 10a. Deploy workflow dispatch (API-level)

```bash
docker compose --profile aws exec backend-aws python3 - <<'PY'
from app.services.deploy_trigger import trigger_deploy_workflow
r = trigger_deploy_workflow(task_id="smoke-test", triggered_by="operator")
print("ok:", r.get("ok"))
print("summary:", r.get("summary", "")[:200])
print("status_code:", r.get("status_code"))
PY
```

**Expected:** `ok: True`, `status_code: 204`

**Note:** This dispatches a real `deploy_session_manager.yml` run — use only during a maintenance window or change `DEPLOY_WORKFLOW_FILE` in a test env.

### 10b. Cursor bridge auth (PR path dry check)

```bash
docker compose --profile aws exec backend-aws python3 - <<'PY'
from app.services.cursor_execution_bridge import _github_auth_configured
from app.services.github_app_auth import get_github_api_token
print("configured:", _github_auth_configured())
_, m = get_github_api_token()
print("method:", m)
PY
```

**Expected:** `configured: True`, `method: github_app`

### 10c. Dashboard integrity workflow auth

Trigger only if you have dashboard admin access — or verify via logs when an operator triggers `dashboard_data_integrity` from the monitoring UI. Expect log line: `auth_method=github_app`.

### 10d. Enable full automation (optional, post-smoke)

Only after all smokes pass:

```bash
export ATP_TRADING_ONLY=0
docker compose --profile aws up -d --force-recreate backend-aws
docker compose --profile aws logs backend-aws --tail=50 | grep -E 'Deploy secrets|RuntimeError'
```

**Expected:** No `RuntimeError` about GitHub credentials.

---

## 11. Legacy PAT removal (final cutover — do last)

> **WARNING:** Do **not** delete `/automated-trading-platform/prod/github_token` until
> `auth_mode: github_app` has been **stable for 24–48 hours**. Keep the PAT as the
> rollback path until then.

**Preconditions:**

- [ ] `verify_deploy_secrets.sh` → `auth_mode: github_app`
- [ ] `verify_github_app_cutover_ready.sh` → `CUTOVER_READY=YES`
- [ ] Deploy dispatch smoke passed
- [ ] Cursor bridge auth smoke passed
- [ ] 24–48h observation with no auth errors in logs

**Steps:**

```bash
# 1. Revoke personal PAT in GitHub UI (Settings → Developer settings → PATs)

# 2. Delete SSM legacy parameter (irreversible — ensure App works first)
aws ssm delete-parameter \
  --region ap-southeast-1 \
  --name /automated-trading-platform/prod/github_token

# 3. Remove GITHUB_TOKEN from .env.aws (fallback source) so a future render
#    in fallback mode cannot resurrect the PAT
cd /home/ubuntu/crypto-2.0
[[ -f .env.aws ]] && sed -i '/^GITHUB_TOKEN=/d' .env.aws

# 4. Re-render on EC2
bash scripts/aws/render_runtime_env.sh
docker compose --profile aws up -d --force-recreate backend-aws

# 5. Recreate backend-aws-canary too, so canary env stays in parity with
#    backend-aws (otherwise the canary keeps stale PAT/App env)
docker compose --profile aws up -d --force-recreate backend-aws-canary

./scripts/verify_deploy_secrets.sh
```

**Expected:** `auth_mode: github_app`, `GITHUB_TOKEN (legacy): no`

---

## 12. Rollback procedure

### 12a. Roll back to legacy PAT (fast)

```bash
# On operator machine — restore PAT to SSM (use your stored PAT value)
export AWS_REGION=ap-southeast-1
export YOUR_LEGACY_PAT="ghp_xxxxxxxxxxxx"

aws ssm put-parameter \
  --region "$AWS_REGION" \
  --name /automated-trading-platform/prod/github_token \
  --value "$YOUR_LEGACY_PAT" \
  --type SecureString \
  --overwrite
```

On EC2:

```bash
cd /home/ubuntu/crypto-2.0
bash scripts/aws/render_and_recreate_backend_safe.sh
# Render summary should show: GITHUB_AUTH_MODE=legacy_transition ALLOW_LEGACY_GITHUB_PAT=YES
```

**Expected:** `auth_mode: legacy_transition` (legacy transition restores deploy automation while the App is fixed)

### 12b. Roll back code (PR #32 revert)

```bash
# On EC2 — deploy previous known-good commit
cd /home/ubuntu/crypto-2.0 || cd /home/ubuntu/automated-trading-platform
git fetch origin
git checkout <LAST_GOOD_SHA>
bash scripts/aws/render_runtime_env.sh
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws up -d backend-aws
```

Or trigger deploy from GitHub Actions after reverting merge on `main`.

### 12c. Roll back GitHub App only

1. Uninstall App from repository (GitHub UI → App → Install App → Configure → Uninstall)
2. Delete SSM `github_app/*` parameters
3. Restore legacy PAT (12a)
4. Re-render and recreate backend

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `auth_method: none` | `ALLOW_LEGACY` absent and App incomplete | Re-run render; check SSM paths |
| `installation token request failed: HTTP 401` | Wrong App ID or bad PEM | Re-encode PEM; verify App ID |
| `installation token request failed: HTTP 404` | Wrong installation ID | Re-fetch from repo installation URL |
| `HTTP 403` on workflow dispatch | App lacks Actions write | Update App permissions; re-install |
| Startup `RuntimeError` | `ATP_TRADING_ONLY=0` without auth | Set `ATP_TRADING_ONLY=1` or fix credentials |
| Render shows `GITHUB_APP=no` | SSM params missing or IAM denied | Check instance role `ssm:GetParameter` |

---

## Related documentation

- [backend/docs/GITHUB_APP_AUTH.md](../../backend/docs/GITHUB_APP_AUTH.md)
- [pr32_deployment_readiness.md](../audits/pr32_deployment_readiness.md)
- [github_auth_transition_gap.md](../audits/github_auth_transition_gap.md)
- [deploy_target_path_validation.md](../audits/deploy_target_path_validation.md)
