# Telegram /task Old Message – Forensic Report

**Date:** 2026-03-19  
**Investigator:** OpenClaw (LAB)  
**Target:** ATP PROD (i-087953603011543c5, ap-southeast-1)  
**Method:** Remote SSM inspection, read-only

---

## 1. Root Cause (Proven)

**The old message comes from stale source code in PROD's `task_compiler.py`.**

| Location | Path | Status |
|----------|------|--------|
| **PROD** | `/home/ubuntu/automated-trading-platform/backend/app/services/task_compiler.py` | **Contains old rejection logic** |
| **LAB** | `backend/app/services/task_compiler.py` | Fixed – low-impact → backlog |

### Evidence

**PROD task_compiler.py lines 469–490** (exact content from SSM grep):

```python
# Creation gate: do not create low-value tasks unless safety pass
if not _value_gate_safety_pass(task, priority_score) and value_score < VALUE_CREATION_THRESHOLD:
    reasons = _rejection_reasons(task, intent_text)
    ...
    return {
        "ok": False,
        "error": "This task has low impact and was not created. If this is important, please clarify urgency or impact.",
        "rejected_low_value": True,
        "reasons": reasons,
    }
```

**LAB task_compiler.py** (current source):

- Line 565: `# Compute priority and value for prioritization only. NEVER block creation.`
- Lines 578–579: `if is_low_impact: task_status = "backlog"` – creates task, does not reject

---

## 2. Forensic Findings

### 2.1 Active PROD Instance

- **Instance ID:** i-087953603011543c5
- **Region:** ap-southeast-1
- **SSM:** Online
- **Repos:** `/home/ubuntu/automated-trading-platform` (preferred), `/home/ubuntu/crypto-2.0`

### 2.2 Source Comparison

| Check | PROD | LAB |
|-------|------|-----|
| Old string in task_compiler.py | **Yes** (line 487) | No |
| Low-impact behavior | Reject with error | Create as backlog |
| `_handle_task_command` path | Same (telegram_commands.py) | Same |

### 2.3 Ruled Out

- **Stale .pyc:** Not checked (containers not running during inspection)
- **Alternate handler:** Same `_handle_task_command` → `create_task_from_telegram_intent` path
- **Alternate token:** Single canonical path; token source not in scope
- **Different container:** No containers observed running; source file is the definitive source

### 2.4 Why Prior Verification Was Misleading

- Verification focused on: single poller, canary `RUN_TELEGRAM_POLLER=false`, log counts.
- The **source file** on PROD was not compared to LAB.
- Deploy may have used cached build or a repo path that was not fully updated.

---

## 3. Minimal Remediation

### 3.1 Fix

Deploy the current LAB code to PROD so `task_compiler.py` matches LAB (low-impact → backlog).

### 3.2 Commands (from LAB)

```bash
# 1. Ensure LAB is pushed
git status
git push origin main

# 2. Deploy with no-cache rebuild (forces fresh image from updated source)
NO_CACHE=1 ./scripts/deploy_production_via_ssm.sh
```

### 3.3 What the Deploy Does

1. `cd /home/ubuntu/automated-trading-platform` (or crypto-2.0)
2. `git fetch origin main && git reset --hard origin/main`
3. `docker compose --profile aws build --no-cache backend-aws`
4. `docker compose --profile aws up -d backend-aws`
5. Health check on port 8002

### 3.4 If Deploy Fails or Repo Is Wrong

If `automated-trading-platform` uses a different remote:

1. Confirm remote: `git remote -v` on PROD
2. If needed, update remote to `https://github.com/ccruz0/crypto-2.0.git`
3. Or run deploy from `crypto-2.0` by changing the deploy script’s `cd` order

---

## 4. Post-Fix Verification

### 4.1 Source Check (SSM)

```bash
aws ssm send-command --instance-ids i-087953603011543c5 --region ap-southeast-1 \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["grep -c \"low impact and was not created\" /home/ubuntu/automated-trading-platform/backend/app/services/task_compiler.py 2>/dev/null || echo 0"]' \
  --timeout-seconds 30 --query 'Command.CommandId' --output text
# Expected: 0 (string removed)
```

### 4.2 Live Test

In ATP Control Telegram:

```
/task test deployment verification
```

**Expected:** Task created (e.g. status Backlog) or a different error – **not** the old "low impact and was not created" message.

### 4.3 Log Check

```bash
# After sending /task, check logs for task_created or task_rejected
docker compose --profile aws logs backend-aws --tail=100 | grep -E "task_created|task_rejected|low_impact"
```

---

## 5. Follow-Up Actions

1. **Confirm deploy path:** Ensure deploy uses the repo that has `origin` → `ccruz0/crypto-2.0`.
2. **Add source verification:** In deploy or verification script, grep for the old string and fail if found.
3. **Optional:** Add a deploy step that compares `task_compiler.py` checksum or key lines with LAB.

---

## 6. Summary

| Item | Result |
|------|--------|
| **Root cause** | Stale `task_compiler.py` on PROD with old rejection logic |
| **Exact source** | `/home/ubuntu/automated-trading-platform/backend/app/services/task_compiler.py` line 487 |
| **Fix** | `NO_CACHE=1 ./scripts/deploy_production_via_ssm.sh` |
| **Verification** | `/task test deployment verification` in ATP Control → task created, no old message |
