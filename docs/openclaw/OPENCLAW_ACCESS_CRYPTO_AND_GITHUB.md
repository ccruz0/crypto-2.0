# Giving OpenClaw (Claw) Access to the Crypto Instance and GitHub

This runbook explains how to let the OpenClaw agent (e.g. Lilo) access:

1. **The crypto instance** — the production EC2 where the trading backend runs (atp-rebuild-2026).
2. **GitHub** — so it can read the repo and documentation (e.g. `automated-trading-platform` or `crypto-2.0`).

It also addresses the **`aws: Permission denied`** error you see in the OpenClaw chat when the agent tries to run the AWS CLI.

---

## Current situation (from your chat)

- The **LAB** instance (atp-lab-ssm-clean), where OpenClaw runs, has **EC2_SSM_Role** attached, so the *host* can use AWS (e.g. SSM, metadata).
- The **agent inside OpenClaw** gets `sh: 1: aws: Permission denied` because the **gateway restricts which executables** the agent is allowed to run. The `aws` CLI is currently blocked by that execution policy, not by IAM.

So we need to:

- **For GitHub:** Ensure the agent (or the OpenClaw app) can use a GitHub token to read the repo and docs.
- **For the crypto instance:** Either allow the agent to run `aws` (and then use IAM/SSM), or give it access via an alternative (e.g. HTTP API or pre-run scripts).

---

## 1. GitHub access (repo + documentation)

OpenClaw is designed to use a **GitHub fine-grained Personal Access Token (PAT)** so it can clone the repo and call the GitHub API. The repo *is* the source of documentation.

### 1.1 Create a fine-grained PAT (if you don’t have one)

1. GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens**.
2. **Generate new token**:
   - Repository access: only the repo(s) you want (e.g. `ccruz0/automated-trading-platform` or `ccruz0/crypto-2.0`).
   - Permissions:
     - **Contents:** Read and write (for clone, branch, push to non-protected branches).
     - **Pull requests:** Read and write (for creating/updating PRs).
     - **Metadata:** Read-only (required).
3. Copy the token once; you won’t see it again.

### 1.2 Put the token on the LAB instance (where OpenClaw runs)

On **LAB** (atp-lab-ssm-clean), e.g. via SSM Session Manager:

```bash
mkdir -p ~/secrets
chmod 700 ~/secrets
touch ~/secrets/openclaw_token
chmod 600 ~/secrets/openclaw_token

# Paste your PAT when prompted (no echo)
read -r -s -p 'Paste GitHub fine-grained PAT: ' TOKEN
echo -n "$TOKEN" > ~/secrets/openclaw_token
unset TOKEN
```

Ensure the OpenClaw container mounts this file and gets only the *path* in env (no token in env). In this repo, `docker-compose.openclaw.yml` already does:

- Mount: `~/secrets/openclaw_token` → `/run/secrets/openclaw_token` (read-only).
- Env: `OPENCLAW_TOKEN_FILE=/run/secrets/openclaw_token`.

Restart OpenClaw after creating or updating the token:

```bash
cd ~/automated-trading-platform
docker compose -f docker-compose.openclaw.yml up -d --force-recreate
```

### 1.3 Ensure the OpenClaw app uses the token

The **OpenClaw application** (gateway/backend in the OpenClaw repo) must:

- Read the token **only** from the path in `OPENCLAW_TOKEN_FILE`.
- Use it for `git clone` / `git fetch` and GitHub API (e.g. to read repo contents and docs).

If the app doesn’t yet use this file, apply the audit and code changes described in **docs/openclaw/PROMPT_AUDIT_OPENCLAW_SOURCE.md** in the OpenClaw source repo.

### 1.4 Repo and docs in one go

Once the token is set and the app uses it:

- **Repo:** OpenClaw can clone the repo (e.g. `automated-trading-platform`) over HTTPS using the PAT.
- **Documentation:** All docs under `docs/` in that repo are part of the clone; the agent can read them from the workspace. If OpenClaw has a “Resources / Docs” feature, you can also add links to the repo or to specific doc paths (e.g. `https://github.com/ccruz0/automated-trading-platform/tree/main/docs` or raw URLs) so the agent is explicitly given those as context.

So: **giving Claw GitHub access via this PAT gives it both the repo and the documentation** that lives in the repo.

---

## 2. Crypto instance access

“Crypto instance” here means the **production** EC2 (atp-rebuild-2026) where the trading backend and Crypto.com integration run.

Two approaches:

### Option A — Allow the agent to run the AWS CLI (recommended if you want SSM/EC2 from chat)

The `Permission denied` for `aws` is due to the **OpenClaw gateway’s execution allowlist**, not IAM. The LAB host already has `EC2_SSM_Role`.

1. **In the OpenClaw gateway/agent config** (in the OpenClaw **application** repo, not this one):
   - Find where allowed executables or shell commands are configured (e.g. “exec allowlist”, “allowed commands”, “sandbox”).
   - Add `aws` (or the full path, e.g. `/usr/local/bin/aws`) to the allowlist so the agent is allowed to run it.
   - Restart the gateway after changing config.

2. **IAM (if the agent should run SSM against PROD):**
   - If you want the agent to run commands on the **crypto instance** via SSM, the **LAB** instance role needs permission to send commands to that instance, e.g.:
     - `ssm:SendCommand` for the PROD instance (resource `arn:aws:ec2:ap-southeast-1:*:instance/i-087953603011543c5` or by tag),
     - and the PROD instance must have SSM agent and an instance role that allows `ssm:UpdateInstanceInformation` (usually already with `EC2_SSM_Role`).
   - After that, the agent could run, for example:
     - `aws ssm send-command --instance-ids i-087953603011543c5 --document-name "AWS-RunShellScript" --parameters '{"commands":["curl -s http://127.0.0.1:8002/api/health"]}' --region ap-southeast-1`
   - You can restrict the policy to specific SSM documents and instance IDs for safety.

3. **Tell Lilo exactly what you need**  
   In the chat you can say, for example: “I want you to run read-only checks on the production instance i-087953603011543c5 via AWS SSM (e.g. health endpoint, or list processes).” Then, once `aws` is allowed and IAM is set, the agent can use `aws ssm send-command` or similar.

### Option B — No AWS CLI for the agent (alternative)

If you prefer **not** to allow the agent to run `aws`:

- **Read-only status from PROD:** Expose a small HTTP endpoint on the **crypto instance** (e.g. `/api/status` or `/api/health`) and allow the LAB instance to reach it (security group: allow LAB’s private IP to PROD on 80/443 or the backend port). Then configure the agent to be allowed to run `curl`, and it can do `curl https://dashboard.hilovivo.com/api/health` (or an internal URL) to “see” the crypto instance’s status.
- **Docs:** Don’t rely on the crypto instance for docs; use GitHub (section 1) so Claw reads the repo and `docs/` from there.

---

## 3. Grant access — do this next

Follow these steps in order to actually grant Claw access.

### Step 1 — GitHub PAT and token on LAB

1. **Create a fine-grained PAT** (see §1.1 above): GitHub → Settings → Developer settings → Fine-grained tokens. Repository access = this repo; Permissions: Contents (R/W), Pull requests (R/W), Metadata (Read). Copy the token.
2. **Connect to LAB** (from your Mac with AWS CLI configured):
   ```bash
   aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
   ```
3. **On LAB**, create the token file (paste your PAT when prompted):
   ```bash
   mkdir -p ~/secrets && chmod 700 ~/secrets
   touch ~/secrets/openclaw_token && chmod 600 ~/secrets/openclaw_token
   read -r -s -p 'Paste GitHub fine-grained PAT: ' TOKEN && echo -n "$TOKEN" > ~/secrets/openclaw_token && unset TOKEN
   ```
4. **Restart OpenClaw** on LAB:
   ```bash
   cd ~/automated-trading-platform && docker compose -f docker-compose.openclaw.yml up -d --force-recreate
   ```
5. **Verify:** `docker exec openclaw env | grep OPENCLAW_TOKEN_FILE` should show `OPENCLAW_TOKEN_FILE=/run/secrets/openclaw_token`. The OpenClaw app must read that file for git/API (see §1.3; if unsure, apply [PROMPT_AUDIT_OPENCLAW_SOURCE.md](PROMPT_AUDIT_OPENCLAW_SOURCE.md) in the OpenClaw repo).

**Optional:** Run the helper script from this repo (from your Mac) to print these commands or run them via SSM: `./scripts/openclaw/grant_openclaw_access_lab.sh` (see §5).

### Step 2 — Allow the agent to run `aws` (fix Permission denied)

The gateway in the **OpenClaw application repo** (not this repo) controls which executables the agent can run.

1. Open the **OpenClaw** source repo (e.g. `ccruz0/openclaw`).
2. Find the **exec allowlist** / **allowed commands** / **sandbox** config (e.g. in gateway config, agent config, or env like `ALLOWED_EXECUTABLES`).
3. **Add `aws`** (or `/usr/local/bin/aws` / path where `aws` is installed on the host running the agent).
4. Rebuild and redeploy the OpenClaw gateway, or restart the service so the new config is loaded.

After this, in the OpenClaw chat the agent should be able to run `aws` without "Permission denied". It will still need IAM (Step 3) to run SSM against PROD.

### Step 3 — IAM: Let LAB send SSM commands to PROD (crypto instance)

So that when the agent runs `aws ssm send-command`, it can target the **production** instance (crypto instance).

1. **Create an IAM policy** that allows SendCommand only to the PROD instance. A ready-made policy is in this repo: **`docs/openclaw/iam-lab-ssm-to-prod-policy.json`**.
2. **Attach the policy to the LAB instance role:**
   - In AWS Console: **IAM** → **Roles** → select the role attached to **atp-lab-ssm-clean** (e.g. `EC2_SSM_Role` or `atp-lab-ssm-role`).
   - **Add permissions** → **Create inline policy** (or **Attach policies** → create a new policy from the JSON).
   - Paste the contents of `iam-lab-ssm-to-prod-policy.json`, then name and save (e.g. `LabSendCommandToProd`).
3. **Confirm PROD has SSM:** EC2 → Instances → atp-rebuild-2026 → Connect → Session Manager should work. PROD must have an instance role with `AmazonSSMManagedInstanceCore` (e.g. `EC2_SSM_Role`).

After Step 2 and 3, in the OpenClaw chat you can tell Lilo: *"Run a read-only check on the production instance i-087953603011543c5 via SSM, e.g. curl http://127.0.0.1:8002/api/health"* and the agent can use `aws ssm send-command` to do it.

### Step 4 — Tell the agent what you want

In the OpenClaw chat, be specific:

- **Repo/docs:** *"Use the GitHub token from OPENCLAW_TOKEN_FILE to clone the repo and read the docs under docs/."*
- **Crypto instance:** *"You can run read-only checks on the production instance i-087953603011543c5 via AWS SSM (e.g. health endpoint, docker ps, or list processes). Use aws ssm send-command with document AWS-RunShellScript."*

---

## 4. Quick checklist

| Goal | Action |
|------|--------|
| **Claw can read the repo** | Create fine-grained PAT (Contents R/W, Pull requests R/W, Metadata R), put it in `~/secrets/openclaw_token` on LAB, mount + `OPENCLAW_TOKEN_FILE` in OpenClaw; ensure OpenClaw app reads that file for git/API. |
| **Claw can read the documentation** | Same as above — docs are in the repo; clone = docs available. Optionally add repo/docs URLs to OpenClaw “Resources / Docs” if available. |
| **Claw can access the crypto instance** | (A) In OpenClaw gateway, allow the agent to execute `aws`; add IAM on LAB for `ssm:SendCommand` to PROD if needed; tell Lilo you want SSM read-only checks on PROD. Or (B) expose a status URL on PROD and allow the agent to run `curl` to that URL. |
| **Fix `aws: Permission denied` in chat** | In the OpenClaw **application** repo, add `aws` to the agent’s execution allowlist and restart the gateway. |

---

## 5. Helper script and IAM policy (this repo)

- **`scripts/openclaw/grant_openclaw_access_lab.sh`** — Run from your Mac. With no args, prints the exact commands to run on LAB for token setup and OpenClaw restart. With `--run`, runs them on LAB via SSM (you still paste the PAT when prompted in the SSM session).
- **`docs/openclaw/iam-lab-ssm-to-prod-policy.json`** — IAM policy to attach to the LAB instance role so the agent can run `aws ssm send-command` against the PROD instance only. See Step 3 above.

---

## 6. References in this repo

- **GitHub token setup on LAB:** [docs/openclaw/LAB_SETUP_AND_VALIDATION.md](LAB_SETUP_AND_VALIDATION.md), [docs/openclaw/RUNBOOK_SECURE_INSTALL.md](RUNBOOK_SECURE_INSTALL.md).
- **Token security (no env fallback):** [docs/openclaw/PROMPT_AUDIT_OPENCLAW_SOURCE.md](PROMPT_AUDIT_OPENCLAW_SOURCE.md), [docs/openclaw/VERIFY_OPENCLAW_CONTAINER.md](VERIFY_OPENCLAW_CONTAINER.md).
- **Instance IDs and roles:** [docs/runbooks/INSTANCE_SOURCE_OF_TRUTH.md](../runbooks/INSTANCE_SOURCE_OF_TRUTH.md), [.cursor/rules/aws-prod-instance.mdc](../../.cursor/rules/aws-prod-instance.mdc).
- **Architecture (LAB vs PROD, no LAB→PROD secrets):** [docs/openclaw/ARCHITECTURE.md](ARCHITECTURE.md).
