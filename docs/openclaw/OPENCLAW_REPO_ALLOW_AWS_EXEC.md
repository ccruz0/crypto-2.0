# OpenClaw repo: Allow agent to run `aws` CLI

**Apply this in the OpenClaw application repo** (e.g. `ccruz0/openclaw`), not in automated-trading-platform.

## Goal

The agent (e.g. Lilo) gets `sh: 1: aws: Permission denied` when it tries to run the AWS CLI. The LAB instance has the correct IAM role and can run `aws` when you SSM in; the blocker is the **gateway’s execution allowlist** (sandbox) that decides which executables the agent is allowed to run.

Add `aws` (and optionally `curl`) to that allowlist so the agent can run read-only checks on the production instance via `aws ssm send-command`.

## Steps (in the OpenClaw repo)

1. **Find where the allowlist is defined**
   - Search for: `allowedExecutables`, `allowed_commands`, `execAllowlist`, `sandbox`, `ALLOWED_EXEC`, `whitelist`, or similar.
   - Likely in: gateway config (JSON/YAML), agent config, or env (e.g. `ALLOWED_EXECUTABLES=git,curl,npm,...`).

2. **Add `aws`**
   - If it’s a list: add `aws` (or the full path, e.g. `/usr/local/bin/aws` if the image uses that path).
   - If it’s env: append `,aws` or add `aws` to the list.

3. **Optional: add `curl`**  
   So the agent can hit health/status URLs (e.g. `curl -s https://dashboard.hilovivo.com/api/health`).

4. **Rebuild and redeploy**  
   Rebuild the OpenClaw image, push, and redeploy on LAB (or restart the gateway so it reloads config).

## Verification

In the OpenClaw chat, ask the agent to run:

```bash
aws sts get-caller-identity
```

or

```bash
aws ssm send-command --instance-ids i-087953603011543c5 --document-name AWS-RunShellScript --parameters '{"commands":["curl -s http://127.0.0.1:8002/api/health"]}' --region ap-southeast-1
```

You should no longer see `Permission denied` for `aws`.

## Reference

- IAM for LAB to send SSM to PROD is already set (policy `LabSendCommandToProd` on role `EC2_SSM_Role`) from the automated-trading-platform runbook.
- Runbook: [OPENCLAW_ACCESS_CRYPTO_AND_GITHUB.md](OPENCLAW_ACCESS_CRYPTO_AND_GITHUB.md).
