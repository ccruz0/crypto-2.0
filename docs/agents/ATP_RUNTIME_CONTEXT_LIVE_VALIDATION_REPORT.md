# ATP Runtime Context — Live Validation Report

**Date:** 2025-03-16  
**Environment:** PROD (i-087953603011543c5), LAB (i-0d82c172235770a0d)  
**Region:** ap-southeast-1

---

## Executive Summary

**Verdict: NOT FIXED (deployment required)**

The runtime-context prompt injection fix exists in the codebase but has **not been deployed** to PROD. Live validation cannot complete until the backend image is rebuilt and redeployed.

---

## A. PROD Environment Status

| Check | Result |
|-------|--------|
| SSM PingStatus | Online |
| boto3 | Installed (import succeeds) |
| AWS credentials | Available (get_caller_identity succeeds) |
| `_fetch_atp_runtime_context` | **NOT PRESENT** — `ImportError: cannot import name '_fetch_atp_runtime_context'` |
| `build_investigation_prompt` with runtime | **N/A** — depends on above |

**Root cause:** The PROD backend container image was built before the fix was added. The `openclaw_client.py` in the deployed image does not contain `_fetch_atp_runtime_context` or the runtime-injection logic.

---

## B. Runtime Context Fetch Result

**Cannot be tested** — the function does not exist in the deployed backend.

---

## C. Prompt Evidence

**Cannot be captured** — prompt builders in the deployed code do not call `_fetch_atp_runtime_context`. The fix is in the repo but not in the running container.

---

## D. OpenClaw Log Evidence (LAB)

**Evidence of current (pre-fix) behavior:**

```
2026-03-16T05:51:33.395+00:00 [tools] exec failed: sh: 1: docker: Permission denied

Command not found
```

This confirms:
- OpenClaw's agent/tool attempted to run `docker` locally
- The command failed with "Permission denied" (or "Command not found")
- This is the exact failure mode the fix is designed to prevent

---

## E. Investigation Output Evidence

**Cannot be captured** — no investigation was run with the fix, since the fix is not deployed.

---

## F. Final Verdict

| Verdict | Explanation |
|---------|-------------|
| **NOT FIXED** | The fix is in the codebase but not deployed. PROD backend must be rebuilt and redeployed. |

---

## Required Actions

1. **Deploy the fix to PROD**
   - Rebuild the backend-aws image (includes `openclaw_client.py` with `_fetch_atp_runtime_context` and runtime injection in all four prompt builders)
   - Redeploy backend-aws to PROD
   - Ensure boto3 and AWS credentials/instance role are available for SSM (already verified)

2. **Re-run live validation after deploy**
   - Run: `./scripts/diag/validate_atp_runtime_context_prod_via_ssm.sh`
   - Or use the Python script: `docker compose --profile aws exec -T backend-aws python scripts/diag/validate_atp_runtime_context_prod.py`
   - Trigger one ATP investigation (Notion task pickup or scheduler)
   - Check OpenClaw LAB logs for absence of new `docker: Permission denied` / `sudo: Permission denied` lines
   - Inspect investigation artifact for use of pre-fetched runtime context

3. **Baseline for post-deploy comparison**
   - Current OpenClaw logs show `docker: Permission denied` at 2026-03-16T05:51:33
   - After deploy, new investigation runs should not produce similar lines

---

## Validation Commands Used

```bash
# PROD: verify _fetch_atp_runtime_context exists and returns data
./scripts/diag/validate_atp_runtime_context_prod_via_ssm.sh

# LAB: fetch OpenClaw logs
aws ssm send-command --instance-ids i-0d82c172235770a0d --region ap-southeast-1 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker logs openclaw --tail 80 2>&1"]' \
  --timeout-seconds 60
```

---

## Files Touched (for deploy)

- `backend/app/services/openclaw_client.py` — `_fetch_atp_runtime_context`, runtime injection in `build_investigation_prompt`, `build_monitoring_prompt`, `build_telegram_alerts_prompt`, `build_execution_state_prompt`
- `backend/scripts/diag/validate_atp_runtime_context_prod.py` — validation script (optional, for post-deploy checks)
- `scripts/diag/validate_atp_runtime_context_prod_via_ssm.sh` — SSM wrapper for validation
