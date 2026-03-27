# OpenClaw ATP Access and Approval Flow Fix

**Date:** 2026-03-13  
**Scope:** ATP connectivity, Telegram approval spam, investigation artifact persistence

---

## 1. Root Cause Analysis

### A. ATP Instance Connectivity

**Problem:** OpenClaw reported name resolution/connectivity issues and fell back to suggesting manual SSH.

**Root cause:** OpenClaw runs on LAB (172.31.3.214) with read-only workspace. It had no way to run operational commands (docker status, logs, health checks) on the ATP PROD instance. The AI output suggested manual SSH as a workaround.

**Fix:** Added ATP command execution API and SSM runner:
- `POST /api/agent/run-atp-command` — runs allowed commands via AWS SSM on PROD
- Auth: `Authorization: Bearer <OPENCLAW_API_TOKEN>`
- Allowed: `docker compose ps`, `docker compose logs --tail=N`, `curl http://127.0.0.1:8002/ping_fast`, `df -h /`, `free -h`
- Denied: `sudo`, `rm -rf`, `git push`, deploy, etc.

### B. Telegram Approval Spam

**Problem:** Too many approval-style messages; human approval requested before a real patch existed.

**Root cause:** 
- Investigation info was sent every time a task completed (could repeat on retries)
- Deploy approval had 24h dedup but investigation info did not
- No clear separation between INFO vs APPROVAL REQUIRED

**Fix:**
- Added 24h dedup for `send_investigation_complete_info`
- `send_investigation_complete_info` is INFO only (no approval buttons)
- `send_patch_deploy_approval` only sends approval when artifact exists; otherwise sends concise info
- Deploy approval already had 24h dedup

### C. Investigation Artifact Persistence

**Problem:** Investigation succeeded → approval → recovery failed with "Investigation artifact was missing or empty", "No sections sidecar found" → task reset to planned.

**Root cause:**
- Sidecar was only written when `sections` was truthy; parsing could return minimal dict
- Recovery `_try_regenerate_from_raw_content` rejected `_preamble`-only sections
- No validation before advancing to investigation-complete
- Recovery reset without logging what existed

**Fix:**
- Always write sidecar when writing md (fallback to `{"_preamble": content}`)
- Allow regeneration from `_preamble`-only sections
- Validate artifact exists and has ≥200 chars before advancing to investigation-complete
- Improved recovery logging (md_exists, md_size, sidecar_exists) before reset

---

## 2. Files Changed

| File | Change |
|------|--------|
| `backend/app/services/agent_recovery.py` | Regenerate from _preamble; better logging before reset |
| `backend/app/services/agent_callbacks.py` | Always write sidecar; fallback to _preamble |
| `backend/app/services/agent_task_executor.py` | Validate artifact before advancing to investigation-complete |
| `backend/app/services/agent_telegram_approval.py` | Investigation info dedup (24h); deploy approval unchanged |
| `backend/app/services/atp_ssm_runner.py` | **New** — SSM command runner with allowlist |
| `backend/app/api/routes_agent.py` | **New** — `POST /agent/run-atp-command`, `GET /agent/atp-instance-info` |
| `backend/app/services/openclaw_client.py` | Add _ATP_COMMAND_NOTE to bug and monitoring prompts |

---

## 3. Config / Env Vars

| Var | Purpose | Default |
|-----|---------|---------|
| `OPENCLAW_API_TOKEN` | Auth for run-atp-command (same as gateway) | Required |
| `ATP_SSM_INSTANCE_ID` | PROD instance for SSM | i-087953603011543c5 |
| `ATP_SSM_REGION` | AWS region | ap-southeast-1 |
| `ATP_PROJECT_PATH` | Project path on instance | /home/ubuntu/crypto-2.0 |

---

## 4. Validation Checklist

- [ ] OpenClaw can reach ATP via `POST /api/agent/run-atp-command` with gateway token
- [ ] OpenClaw no longer suggests manual SSH for normal operational tasks
- [ ] Investigation completes and persists artifact (.md + .sections.json)
- [ ] Telegram shows INFO updates without approval spam
- [ ] Approval requested only once when patch is ready (deploy approval)
- [ ] Recovery does not fail when sidecar exists; uses markdown if sidecar missing
- [ ] Task does not reset when valid artifact exists
- [ ] Safety gates remain for deploy approval

---

## 5. Quick Test

```bash
# 1. ATP command API (requires OPENCLAW_API_TOKEN)
curl -X POST https://dashboard.hilovivo.com/api/agent/run-atp-command \
  -H "Authorization: Bearer $OPENCLAW_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "docker compose --profile aws ps"}'

# 2. Instance info (no auth)
curl https://dashboard.hilovivo.com/api/agent/atp-instance-info
```

---

## 6. AWS Credentials for run-atp-command

The backend runs in Docker and may not have access to the EC2 instance metadata service. If you see `"error":"Unable to locate credentials"` from `run-atp-command`, add explicit AWS credentials:

1. **Create IAM user** (or use existing deploy user) with minimal SSM permissions. Example inline policy:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": ["ssm:SendCommand", "ssm:GetCommandInvocation", "ssm:ListCommands"],
       "Resource": [
         "arn:aws:ec2:ap-southeast-1:YOUR_ACCOUNT:instance/i-087953603011543c5",
         "arn:aws:ssm:ap-southeast-1::document/AWS-RunShellScript"
       ]
     }]
   }
   ```
   Replace `YOUR_ACCOUNT` with your AWS account ID.

2. **Store credentials in SSM Parameter Store** (encrypted). From a machine with AWS CLI configured (same creds as deploy):
   ```bash
   ./scripts/aws/store_aws_creds_for_atp_ssm.sh
   ```
   Or manually:
   ```bash
   aws ssm put-parameter --name /automated-trading-platform/prod/aws_access_key_id \
     --value "AKIA..." --type SecureString --overwrite --region ap-southeast-1
   aws ssm put-parameter --name /automated-trading-platform/prod/aws_secret_access_key \
     --value "..." --type SecureString --overwrite --region ap-southeast-1
   ```

3. **Re-render and deploy**:
   ```bash
   # On instance (or locally with AWS creds):
   bash scripts/aws/render_runtime_env.sh
   docker compose --profile aws restart backend-aws
   ```

4. **Verify**:
   ```bash
   curl -X POST https://dashboard.hilovivo.com/api/agent/run-atp-command \
     -H "Authorization: Bearer $OPENCLAW_API_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"command": "docker compose --profile aws ps"}'
   ```

---

## 7. OpenClaw Integration

For OpenClaw to use the ATP command API, it needs an HTTP client. Options:

1. **Add a custom tool** in the OpenClaw repo that calls the API
2. **Add a skill** in openclaw-home-data (if OpenClaw supports HTTP tools)
3. **Prompt-only** — The prompts now instruct the AI to use the API; if OpenClaw has a generic HTTP tool, it can call it

The prompt text is in `_ATP_COMMAND_NOTE` in `openclaw_client.py`.
