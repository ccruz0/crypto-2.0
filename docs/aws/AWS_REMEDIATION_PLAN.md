# AWS Remediation Plan

**Based on:** docs/aws/AWS_LIVE_AUDIT.md, docs/aws/AWS_ARCHITECTURE.md  
**Region:** ap-southeast-1  
**Scope:** Documentation only. No infrastructure or AWS changes.

---

## 1. Production Verification Gap

### Why atp-rebuild-2026 Could Not Be Verified

- **SSM PingStatus** at audit time was **ConnectionLost**.
- **SSM Run Command** returned **Undeliverable**: the agent on the production instance did not receive the command.
- Possible causes (see docs/audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md): VPC endpoint security group blocking ec2messages/ssmmessages, instance subnet/NACL, SSM agent not running or not registered, network path to SSM endpoints down.

### Risk Created

- **Unverified runtime:** Unknown whether the full trading stack (backend-aws, frontend-aws, market-updater-aws, db, observability) is running.
- **Unverified single-runtime:** Cannot confirm that only one production runtime is active (no duplicate Telegram pollers or local + AWS backends).
- **Unverified security:** Cannot confirm listening ports (e.g. 8002, 3000 bound to 127.0.0.1 only) or absence of rogue processes.
- **Operational blind spot:** If SSM stays unreachable, operators cannot use Session Manager for deploy, restart, or health checks without SSH or physical access.

### What Must Be Validated

1. SSM connectivity restored (PingStatus = Online).
2. Expected Docker Compose `aws` profile services running.
3. No ports bound to 0.0.0.0 except where documented (e.g. none for app ports).
4. No duplicate trading/signal/scheduler processes; single active production runtime.
5. Environment variables (ENVIRONMENT=aws, RUNTIME_ORIGIN=AWS, TRADING_ENABLED) consistent with production.

### Exact SSM Command Blocks for Validation

Run these **on atp-rebuild-2026** after connecting via **EC2 → Instances → atp-rebuild-2026 → Connect → Session Manager**:

```bash
# 1) Docker containers
docker ps

# 2) Docker Compose services (aws profile)
cd /home/ubuntu/automated-trading-platform
docker compose --profile aws ps

# 3) Listening ports
sudo ss -tulpn

# 4) Running systemd services
systemctl list-units --type=service --state=running

# 5) Trading-related processes (confirm single backend / market-updater)
ps aux | grep -E "signal|trade|scheduler|exchange|gunicorn|market" | grep -v grep
```

### Step-by-Step Checklist for Production Verification

Use this once SSM is Online on atp-rebuild-2026.

| Step | Check | Pass criteria |
|------|--------|----------------|
| 1 | **Trading stack running** | `docker compose --profile aws ps` shows backend-aws, frontend-aws, market-updater-aws, db in running state. |
| 2 | **Monitoring running** | Same output shows prometheus, grafana, alertmanager, telegram-alerts, node-exporter, cadvisor (or documented subset) running. |
| 3 | **No rogue processes** | `ps aux | grep -E "signal|trade|scheduler|exchange|gunicorn|market"` shows only processes belonging to expected containers (e.g. gunicorn in backend-aws, run_updater in market-updater-aws). No extra Python/Node processes running same stack. |
| 4 | **No duplicate pollers** | Exactly one market-updater-aws (or equivalent) process; no second SignalMonitorService or Telegram long-polling loop on this host or documented as running elsewhere for same env. |
| 5 | **Ports bound correctly** | `ss -tulpn` shows 8002, 3000, 9090, 3001, 9093, 9100, 8080 on 127.0.0.1 or docker bridge only; no 0.0.0.0 for app ports. |
| 6 | **Health endpoint** | `curl -s http://localhost:8002/health` returns OK; `curl -s http://localhost:8002/api/health/system` returns expected payload. |
| 7 | **Env consistency** | Container env (e.g. `docker compose --profile aws exec backend-aws env | grep -E 'ENVIRONMENT|RUNTIME_ORIGIN|TRADING_ENABLED'`) shows ENVIRONMENT=aws, RUNTIME_ORIGIN=AWS, TRADING_ENABLED=true. |

---

## 2. Security Hardening Actions

Findings from the audit and architecture docs are classified below. All actions are **recommendations**; implement only after approval and change process.

### 🔴 Critical

| Action | Rationale |
|--------|-----------|
| **Restore SSM connectivity on production** | Without SSM, production cannot be verified or operated via the documented SSM-first model. Follow docs/audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md (VPC endpoint SGs, ec2messages/ssmmessages reachability, agent restart). |
| **Confirm single production runtime** | Architecture states "AWS is the ONLY live production runtime." Verify no local or other EC2 backend is running SignalMonitorService/scheduler/Telegram in parallel to avoid duplicate orders and alerts. |
| **Confirm single Telegram poller** | Only one process should be long-polling the Telegram bot for production; duplicate pollers cause 409 conflicts and duplicate alerts. Validate via process list and logs. |

### 🟠 Important

| Action | Rationale |
|--------|-----------|
| **Evaluate public IP on production** | Production has public IP 52.77.216.100. If no ALB or direct public access is required, consider moving to private subnet + NAT or removing auto-assign public IP to reduce attack surface. Document the decision. |
| **Enforce SSM-only access** | Architecture is SSM-first; inbound SG is already empty. Ensure no inbound rule for port 22 is added for production. Use SSM for all operator access; use SSH only as break-glass with key and temporary SG change if ever needed. |
| **Restrict outbound SG** | Align with docs/audit/EGRESS_HARDENING_DESIGN.md: outbound HTTPS 443, HTTP to 169.254.169.254/32, DNS 53. Remove "All traffic" to 0.0.0.0/0 if present. |
| **Rename PROD security group** | Current PROD SG is launch-wizard-6 (sg-07f5b0221b7e69efe). Align with naming: e.g. atp-prod-sg for clarity and automation. (Documentation/runbook change only here; actual rename is an AWS change.) |

### 🟢 Optional Improvement

| Action | Rationale |
|--------|-----------|
| **Disable sshd at OS level on instances that are SSM-only** | Lab (and PROD if SSH is never used) can run `sudo systemctl disable --now ssh` to reduce surface. Re-enable only for break-glass. Document the decision and procedure. |
| **Use dedicated lab IAM role** | Architecture allows atp-lab-ssm-role for lab. If both instances use EC2_SSM_Role today, consider attaching atp-lab-ssm-role to lab instance for clearer separation (IAM change; document only here). |
| **Secrets in Parameter Store/Secrets Manager** | Architecture mentions migrating from secrets/runtime.env to SSM Parameter Store or Secrets Manager. Plan and document the migration steps; no change in this doc. |

---

## 3. Runtime Conformity Matrix

| Instance | Role | Expected (from AWS_ARCHITECTURE.md) | Actual (from AWS_LIVE_AUDIT.md) | Action Required |
|----------|------|-------------------------------------|----------------------------------|------------------|
| atp-rebuild-2026 | **Production** | Full aws profile stack; trading + Telegram; SSM access; optional public IP; ports on 127.0.0.1 | Not verified (SSM ConnectionLost); public IP present; IAM EC2_SSM_Role; SG inbound empty | 1) Restore SSM. 2) Run Section 1 verification commands. 3) Update AWS_LIVE_AUDIT.md with results. |
| atp-lab-ssm-clean | **Lab** | Experiments; may have no public IP; SSM access; no requirement to run full stack | No ATP stack; no public IP; SSM Online; sshd listening but SG blocks inbound; EC2_SSM_Role | None for conformity. Optional: disable sshd if SSM-only; consider atp-lab-ssm-role. |

---

## 4. Operational Guardrails

### One Poller Rule

- **Rule:** Exactly one process (or process group) must perform Telegram bot long-polling for the production bot token.
- **Implementation:** Run only one backend or market-updater instance that sets RUN_TELGRAM=true and uses TELEGRAM_BOT_TOKEN_AWS in production. Do not run a second instance (e.g. local Mac or another EC2) with the same token and polling enabled.
- **Validation:** On production host, `ps aux | grep -E "telegram|run_updater|gunicorn"` and container list show exactly one such runner; logs show no 409 conflicts from Telegram API.

### One Production Runtime Rule

- **Rule:** AWS EC2 atp-rebuild-2026 is the only live production runtime for trading and alerts. Local or other environments must not run SignalMonitorService, scheduler, or production Telegram in parallel.
- **Implementation:** DEPLOYMENT_POLICY.md and architecture already state this. Enforce via process: before starting local backend with trading/Telegram, confirm AWS stack is stopped or use different tokens/env. In CI/docs: "Production = AWS only."
- **Validation:** Periodic audit (e.g. from this remediation plan): confirm only atp-rebuild-2026 runs the aws profile stack; no other instance or host uses production credentials for trading/alerts.

### Environment Variable Validation

- **Rule:** Production containers must have ENVIRONMENT=aws, APP_ENV=aws, RUNTIME_ORIGIN=AWS. TRADING_ENABLED and RUN_TELEGRAM must match intent (e.g. true for production).
- **Implementation:** In deploy or health script, check container env (e.g. `docker compose --profile aws exec backend-aws env`) for these variables. Alert or fail deploy if inconsistent.
- **Checklist:** Document in runbook: "Pre-deploy: verify runtime.env and .env.aws; post-deploy: curl /api/health and check env in container."

### CI/CD Guardrail Proposal

- **Rule:** Deploys to production (atp-rebuild-2026) must go through a single path (e.g. main branch → SSM Run Command or CodeDeploy), with no direct SSH or ad-hoc run from developer machines for production.
- **Implementation:** Use GitHub Actions (or similar) to run SSM send-command targeting only production instance ID; script runs `git pull` and `bash scripts/aws/aws_up_backend.sh` (or equivalent). No production secrets on CI; use IAM role or OIDC for AWS credentials.
- **Guardrail:** Pipeline step that checks SSM PingStatus for production instance before running deploy; fail if ConnectionLost and notify.

---

## 5. Final Risk Classification

| Environment | Classification | Reason |
|-------------|----------------|--------|
| **Production (atp-rebuild-2026)** | **Production At Risk** | SSM unreachable at audit time; runtime and single-runtime assumption could not be verified. Until SSM is restored and Section 1 verification is completed, production state is unconfirmed. |
| **Lab (atp-lab-ssm-clean)** | **Lab Safe** | No ATP stack, no trading, no public IP, SSM Online, no inbound rules. Matches documented lab role. |

**Overall:** **Requires Immediate Action** for production: restore SSM connectivity and complete the production verification checklist. Lab is in good shape; no immediate action required for lab.

---

## CI Runtime Guard

The workflow **.github/workflows/aws-runtime-guard.yml** runs on push to `main` and on `workflow_dispatch`. It executes `scripts/aws_runtime_verify.py` via AWS SSM against the production instance (atp-rebuild-2026) and fails the job if the runtime is not classified as **PRODUCTION_SAFE**.

- **Deployment blocked if runtime is not PRODUCTION_SAFE:** The job fails when the script exits with code 1 (PRODUCTION_AT_RISK) or 2 (CRITICAL_RUNTIME_VIOLATION). Any downstream deployment that depends on this job will not run until the runtime passes verification.
- **Prevents duplicate pollers:** The verification script checks that exactly one Telegram poller process is present. Multiple pollers cause 409 conflicts and duplicate alerts; the guard fails if more than one is detected.
- **Prevents multiple schedulers:** The script validates that signal monitor and scheduler/trading processes are not duplicated on the production host, enforcing a single active production runtime.
- **Prevents port exposure mistakes:** The script fails if critical app ports (e.g. 8002, 3000) are bound to 0.0.0.0 instead of 127.0.0.1, reducing risk of unintended public exposure.
- **Enforces SSM connectivity:** If the SSM command is Undeliverable or the agent is unreachable, the script returns CRITICAL_RUNTIME_VIOLATION (exit 2). The guard therefore blocks deployment when production cannot be reached via SSM, surfacing connectivity issues before deploy.

Required GitHub secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. The IAM user or role must have permission to run SSM Send Command and Get Command Invocation against the production instance.

---

## Runtime Status Dashboard

### Where to view Guard + Sentinel runs

- **Guard:** `.github/workflows/aws-runtime-guard.yml` — runs on push to `main` and on `workflow_dispatch`. View runs under **Actions → AWS Runtime Guard**.
- **Sentinel:** `.github/workflows/aws-runtime-sentinel.yml` — runs on schedule (daily 02:00 UTC) and on `workflow_dispatch`. View runs under **Actions → AWS Runtime Sentinel**.

### Sentinel artifacts

Sentinel always uploads artifacts when the job runs:

- **runtime-report.json** — Structured report for the last verification run (timestamp, instance, SSM status, containers, processes, ports, checks, classification, remediation).
- **runtime-history/** — Dated copies of reports under `runtime-history/YYYY-MM-DD/production-HHMMSS-<classification>.json`. Download the **runtime-sentinel-artifacts** artifact from the workflow run to inspect history.

### How to interpret classification + key checks

| Classification | Meaning |
|----------------|--------|
| **PRODUCTION_SAFE** | SSM reachable; exactly one Telegram poller; no critical port exposure; scheduler/signal monitor OK. |
| **PRODUCTION_AT_RISK** | SSM reachable but warnings (e.g. no scheduler in process list, or unexpected listeners). |
| **CRITICAL_RUNTIME_VIOLATION** | SSM unreachable/Undeliverable, or critical check failed (duplicate pollers, critical ports on 0.0.0.0, duplicate signal monitors). |

Key checks in the report:

- **telegram_poller_ok** — Exactly one poller process.
- **scheduler_ok** — Trading/scheduler process or containers detected.
- **signal_monitor_ok** — At most one signal monitor.
- **exposed_ports_ok** — No critical app ports (e.g. 8002, 3000) bound to 0.0.0.0.

### ALLOW_AUTO_KILL and when it triggers

- **Secret:** `ALLOW_AUTO_KILL` (optional). When set to `true`, Sentinel may run **containment** (auto-kill) when the runtime is classified **CRITICAL_RUNTIME_VIOLATION**.
- **When it triggers:** Only when the **first** verification run exits with code **2** (CRITICAL) **and** `secrets.ALLOW_AUTO_KILL == 'true'`. In that case, a second run executes with `--auto-kill`, which sends an SSM command on the instance to: stop Docker Compose (aws profile), then `pkill -f 'telegram'`. This is best-effort containment only; it does not change the classification logic.
- **When it does not run:** If the run is PRODUCTION_SAFE (exit 0) or PRODUCTION_AT_RISK (exit 1), no auto-kill is attempted. If CRITICAL but `ALLOW_AUTO_KILL` is not `true`, the Telegram alert will state "auto-kill skipped (ALLOW_AUTO_KILL not true)".

---

*This plan is documentation only. No infrastructure or AWS resources were modified.*
