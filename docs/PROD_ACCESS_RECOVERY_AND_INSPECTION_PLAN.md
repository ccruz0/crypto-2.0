# PROD Access Recovery and Inspection Plan

**Date:** 2026-03-11  
**Purpose:** Regain visibility into PROD (atp-rebuild-2026, i-087953603011543c5) when SSM is ConnectionLost and the API health endpoint times out. No new architecture; reuse existing scripts and runbooks. No code changes in this plan.

**Region:** ap-southeast-1  
**Instance:** i-087953603011543c5 (atp-rebuild-2026)  
**Domain:** dashboard.hilovivo.com

**Incident note:** First post-incident checks on PROD were completed after access was restored. Root disk is not full; memory is tight on t3.small with swap disabled; docker and nginx are active; SSM agent appears inactive from systemctl despite AWS having shown SSM Online. See **Post-Recovery Evidence** below for details, follow-up checklist, and recommendations.

---

## 1. Confirmed Current State

### What we know for sure

- **PROD instance exists and is documented** as the production target (atp-rebuild-2026, i-087953603011543c5). Source: docs/aws/AWS_PROD_QUICK_REFERENCE.md, RUNBOOK_SSM_PROD_CONNECTION_LOST.md, INSTANCE_SOURCE_OF_TRUTH.md.
- **SSM PingStatus for PROD is ConnectionLost** (observed 2026-03-11 via `./scripts/aws/prod_status.sh`). LAB (i-0d82c172235770a0d) is Online.
- **Public API** `https://dashboard.hilovivo.com/api/health` **returns HTTP 000** (timeout/unreachable) from the audit machine (2026-03-11). So either the instance is not reachable on 443, or nginx/backend is not responding.
- **Documented history (2026-02-24):** On this same instance, SSM has remained ConnectionLost after reboot, IAM role reattach, and agent restart. The runbook states the agent fails with "Retrieve credentials produced error." Recommended access when SSM fails: **EC2 Instance Connect** (or Serial Console if that also fails). Source: RUNBOOK_SSM_PROD_CONNECTION_LOST.md § "Estado conocido" and §5.
- **Security group** for PROD is documented as **sg-07f5b0221b7e69efe**. SSH (22) can be opened from "My IP" or EC2 Instance Connect CIDR (e.g. 3.0.5.32/29 for ap-southeast-1) to allow Instance Connect or SSH. Source: COMANDOS_PARA_EJECUTAR.md, open_prod_access.sh, HOW_TO_CONNECT.md.
- **Repo contains** scripts and runbooks for: reboot PROD, restore SSM (restore_ssm_prod.sh), open SSH for Instance Connect (open_prod_access.sh), bring up dashboard (bringup_dashboard_prod.sh), heal nginx (heal_nginx_connection_closed_eice.sh), and Serial Console recovery (PROD_ACCESS_WHEN_SSM_AND_SSH_FAIL.md). No code changes required to use them.

### What is unverified

- **Current EC2 instance state** (running / stopped / stopping) at the time of recovery — must be checked in Console or via `aws ec2 describe-instances`.
- **Current public IP** of PROD (can change after stop/start if no Elastic IP).
- **Whether DNS** dashboard.hilovivo.com still points to the current PROD public IP.
- **Whether EC2 Instance Connect** succeeds (browser terminal). If it fails, the runbook attributes it to disk full and/or sshd/SSM agent not running.
- **Whether port 22** is reachable from the operator’s network to PROD (security group may allow 22 but operator’s ISP may block outbound 22).
- **Root cause** of SSM ConnectionLost (agent, network, IAM, VPC endpoints, or disk/OS).
- **Root cause** of API timeout (instance down, nginx/backend down, network path, or DNS).
- **What health/recovery stack** (timers, services, cron) is actually installed and running on PROD — baseline was not filled because PROD was inaccessible.

---

## 2. Most Likely Failure Scenarios

| Scenario | Confidence | Why it fits the symptoms | Supporting evidence | Missing evidence |
|----------|------------|---------------------------|---------------------|------------------|
| **amazon-ssm-agent stopped or unhealthy** | **High** | ConnectionLost means the agent is not successfully talking to the SSM control plane. Documented "Retrieve credentials produced error" points to agent/credentials. | RUNBOOK_SSM_PROD_CONNECTION_LOST.md states agent fails with that error; reboot/restart have not restored SSM on this instance before. | Current agent status and logs on PROD (cannot collect without access). |
| **Instance reachable by AWS but app not reachable** | **High** | API returns 000 (timeout) — from the internet we cannot reach the app. Instance could be Running with 443 open in SG but nginx/backend down or not listening. | DASHBOARD_AND_OPENCLAW_RECOVERY_ORDER, bringup_dashboard_prod.sh, and DASHBOARD_UNREACHABLE_RUNBOOK assume "instance running but dashboard times out" as a common case. | We have not confirmed instance state (running/stopped) or that 443 is reachable from the internet. |
| **Disk full** | **Medium** | Doc states disk full is the "most common recurring cause" when SSM and Instance Connect both fail: agent/sshd can't write logs and crash. | PROD_ACCESS_WHEN_SSM_AND_SSH_FAIL.md explicitly lists disk full first; PROD_DISK_RESIZE.md exists for FAIL:DISK. | We have no current df/path usage from PROD. |
| **Docker or app stack down** | **Medium** | If backend/nginx are not running, /api/health will not respond. Stack could have crashed or never started after reboot. | AWS_BRINGUP_RUNBOOK and AWS_LIVE_AUDIT describe bringing stack up and checking docker compose / health. | No docker ps or compose output from PROD. |
| **nginx/reverse proxy failure** | **Medium** | Even if backend is up on 127.0.0.1:8002, nginx must proxy 443 → backend. Nginx crash or misconfig → timeout or 502. | heal_nginx_connection_closed_eice.sh, 502 runbooks, DASHBOARD_AND_OPENCLAW_RECOVERY_ORDER. | No nginx status or error logs from PROD. |
| **Instance network path broken (egress)** | **Medium** | SSM agent needs outbound 443 to AWS endpoints. If egress is blocked (SG/NACL/VPC endpoints), agent never registers. | RUNBOOK_SSM_PROD_CONNECTION_LOST.md §3 (VPC endpoints), §4 (outbound 443). SSM audit lists outbound 443 and VPC endpoint SGs. | We don't know if PROD uses VPC endpoints for SSM or current SG/NACL rules. |
| **VPC endpoints for SSM — PROD SG not allowed** | **Medium** | If VPC has SSM interface endpoints and only LAB SG was allowed, PROD cannot reach SSM. Runbook and restore_ssm_prod.sh include a fix (add PROD SG to endpoint SGs). | RUNBOOK_SSM_PROD_CONNECTION_LOST.md §3; restore_ssm_prod.sh Step 3. | Unknown whether this VPC has SSM interface endpoints. |
| **Instance stopped or unreachable** | **Low–Medium** | If instance is stopped, both SSM and API would be unreachable. If instance is running but no public IP (e.g. wrong subnet), API would timeout. | bringup_dashboard_prod.sh handles stopped state; DASHBOARD_UNREACHABLE_RUNBOOK mentions DNS vs IP. | Instance state and public IP not re-checked in this session. |
| **Security group / routing / DNS drift** | **Low** | Inbound 80/443/22 could have been removed or restricted; DNS could point to an old IP after stop/start. | DASHBOARD_UNREACHABLE_RUNBOOK, COMANDOS_PARA_EJECUTAR (SG edit for SSH). | Current SG rules and DNS A record not re-verified. |
| **Memory exhaustion / OOM** | **Low** | OOM can kill SSM agent, sshd, or Docker. Would explain both SSM and app failure. | General knowledge; no specific OOM evidence in repo for this instance. | No memory or OOM logs from PROD. |
| **CPU saturation** | **Low** | Unlikely to cause both SSM and HTTP timeout unless the box is completely unresponsive. | — | No load/cpu evidence. |
| **Broken deploy** | **Low** | A bad deploy could leave backend/nginx in a bad state; would not by itself explain SSM ConnectionLost. | — | No recent deploy evidence. |
| **systemd target not healthy** | **Low** | If the system failed to boot fully, services might not start. Serial Console would show this. | PROD_ACCESS_WHEN_SSM_AND_SSH_FAIL suggests starting ssh + agent from Serial Console. | No boot/log evidence from PROD. |

---

## 3. Existing Repo Tools We Can Reuse

| Script / doc | Use | Safe for inspection only? |
|--------------|-----|---------------------------|
| **scripts/aws/prod_status.sh** | One-shot: curl PROD /api/health + SSM PingStatus for PROD and LAB. | Yes (read-only). |
| **scripts/aws/verify_prod_public.sh [URL]** | Curl a URL (default https://dashboard.hilovivo.com/api/health), exit 0 if 200. | Yes. |
| **scripts/aws/open_prod_access.sh** | Ensure PROD SG allows SSH (22) from EC2 Instance Connect CIDR so browser Connect works. | No (modifies SG). Use when you intend to use Instance Connect. |
| **scripts/aws/restore_ssm_prod.sh** | Reboot PROD → wait → if still ConnectionLost: add SSH from this machine’s IP, push key via EIC, restart SSM agent, VPC endpoint SG fix, IAM replace, then collect agent logs. | No (reboot + SG + commands on box). Use as recovery sequence, not inspection-only. |
| **scripts/aws/bringup_dashboard_prod.sh** | Start instance if stopped, optional reboot if running but curl fails, DNS vs IP warning. | No (start/reboot). Use when instance may be stopped or when you want to try reboot for dashboard. |
| **scripts/aws/heal_nginx_connection_closed_eice.sh** | SSH to PROD via EIC, restart nginx, sync openclaw proxy to LAB:8080. | No (writes on PROD). Use after you have SSH/EIC and want to fix nginx/openclaw. |
| **docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md** | Steps: check PingStatus, reboot, VPC endpoints, diagnose, use Instance Connect or Serial Console. | Yes (reading). Follow steps as needed. |
| **docs/aws/PROD_ACCESS_WHEN_SSM_AND_SSH_FAIL.md** | Enable Serial Console, connect, check disk (df -h /), free space, start ssh + amazon-ssm-agent. | No (Serial Console + commands on box). Use when Instance Connect fails. |
| **docs/aws/COMANDOS_PARA_EJECUTAR.md** | Copy-paste: SG for Instance Connect, reboot PROD, prod_status, verify_prod_public. | Yes (reading); running reboot/SG changes is recovery. |
| **docs/aws/HOW_TO_CONNECT.md** | How to connect: Console (Instance Connect / SSM), SSH, EIC scripts. | Yes. |
| **docs/runbooks/DASHBOARD_AND_OPENCLAW_RECOVERY_ORDER.md** | Order: bringup (A), heal nginx (A2), fix 502 (B), LAB/SSM (C). Verify with verify_prod_public + run_openclaw_diagnosis_local. | Yes (reading). Execute steps as appropriate. |
| **docs/runbooks/DASHBOARD_UNREACHABLE_RUNBOOK.md** | Dashboard timeout: bringup_dashboard_prod, DNS, try other network, reboot, Elastic IP. | Yes (reading). |
| **docs/aws/AWS_BRINGUP_RUNBOOK.md** | Commands to run on EC2 to bring stack to “works perfectly”: env, docker compose, health curls. | Yes when run on instance (inspection + bring-up). |
| **docs/aws/AWS_LIVE_AUDIT.md** | Commands to run on instance (docker ps, compose ps, ss -tulpn, systemctl, processes). | Yes (inspection). |
| **docs/audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md** | SSM diagnosis: agent status, logs, IMDS, DNS, time sync; evidence table. | Yes (inspection when on instance). |
| **docs/runbooks/PROD_DISK_RESIZE.md** | How to resize EBS and grow FS; optional df/docker check via SSM. | Yes (reading); resize is a change. |
| **diagnose_backend_health.sh** | Backend health diagnostic (local or remote SSH). Uses EC2_HOST (old IP in script). | Partially: logic is useful; update host or run on server. Not SSM-based. |
| **check_backend_status.sh** (repo root) | Runs SSM send-command to PROD for backend/nginx/port checks. | Yes only when SSM is Online (otherwise it fails). |
| **fix_backend_docker_build.sh** / **check_and_fix_backend_ssm.sh** | SSM-based backend fix/check. | No (remediation). Use only after access is restored and you intend to fix. |

---

## 4. Safest Recovery Sequence

Order: **inspection-only first** (from your machine and Console), then **safe recovery** (no destructive changes), then **higher-risk** (reboot, SG, Serial Console).

### A. Inspection-only (from your machine / AWS Console)

1. **Instance state and IP**  
   - `aws ec2 describe-instances --region ap-southeast-1 --instance-ids i-087953603011543c5 --query 'Reservations[0].Instances[0].{State:State.Name,PublicIp:PublicIpAddress}' --output table`  
   - If **Stopped**, proceed to “Safe recovery” to start. If **Running**, note PublicIp.

2. **PROD API and SSM status**  
   - `./scripts/aws/prod_status.sh`  
   - `./scripts/aws/verify_prod_public.sh` (and optionally `verify_prod_public.sh https://dashboard.hilovivo.com`).

3. **DNS**  
   - `dig +short dashboard.hilovivo.com A`  
   - Compare to PROD public IP; if different, document for later DNS/Elastic IP fix.

4. **Console checks**  
   - EC2 → Instances → i-087953603011543c5: **Status checks** (System + Instance), **Security** tab (SG, IAM role).  
   - If status checks **Impaired** or **Initializing**, note for reboot decision.

### B. Safe recovery actions (no Serial Console, no disk changes yet)

5. **If instance is Stopped**  
   - Start: `aws ec2 start-instances --region ap-southeast-1 --instance-ids i-087953603011543c5`  
   - Wait 2–3 minutes, then re-run step 1 and 2.

6. **If instance is Running but API still fails**  
   - **Option A — Try reboot (often restores SSM temporarily):**  
     - `aws ec2 reboot-instances --region ap-southeast-1 --instance-ids i-087953603011543c5`  
     - Wait 3–5 minutes. Re-run prod_status.sh and verify_prod_public.sh.  
   - **Option B — Or run full restore_ssm_prod.sh** (reboot + EIC + agent restart + VPC endpoints + IAM replace + log collection):  
     - `./scripts/aws/restore_ssm_prod.sh`  
     - Requires: AWS CLI, ability for script to SSH to PROD (port 22 from your IP). If your network blocks 22, use Console Instance Connect after step 7.

7. **Open SSH for Instance Connect (if needed)**  
   - So that **EC2 → Connect → EC2 Instance Connect** works: add SSH (22) from Instance Connect CIDR or “My IP”.  
   - Either: **Console** → Security group sg-07f5b0221b7e69efe → Edit inbound → Add SSH 22 from My IP, **or** run `./scripts/aws/open_prod_access.sh` (adds EIC CIDR).

8. **Connect via EC2 Instance Connect (browser)**  
   - EC2 → Instances → atp-rebuild-2026 → **Connect** → **EC2 Instance Connect** → **Connect**.  
   - If this **succeeds**: you have a shell. Go to §5 “Minimum commands” and §7 “After access is restored.”  
   - If this **fails** (“Error establishing SSH connection”): treat as sshd/agent down or disk full → go to step 9.

### C. Higher-risk / last-resort

9. **EC2 Serial Console** (when Instance Connect and SSM both fail)  
   - **docs/aws/PROD_ACCESS_WHEN_SSM_AND_SSH_FAIL.md**: enable Serial Console (account), connect to instance, log in.  
   - **First on instance:** `df -h /` — if disk full, free space (journalctl vacuum, apt clean, docker prune) or plan EBS resize (PROD_DISK_RESIZE.md).  
   - Then: `sudo systemctl start ssh`, `sudo systemctl enable ssh`, `sudo systemctl start amazon-ssm-agent`, `sudo systemctl enable amazon-ssm-agent`.  
   - Wait 1–2 minutes, then retry **Session Manager** or **EC2 Instance Connect**.

10. **If SSM becomes Online**  
    - Use **Session Manager** for all further inspection and fixes. Run the baseline commands in §7 and fill docs/ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md §3.

---

## 5. Minimum Commands to Run First

Run these **from your machine** (no PROD shell yet):

```bash
export AWS_REGION=ap-southeast-1
export INSTANCE_ID=i-087953603011543c5

# 1) Instance state and public IP
aws ec2 describe-instances --region $AWS_REGION --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].{State:State.Name,PublicIp:PublicIpAddress}' --output table

# 2) PROD API + SSM status
cd /path/to/automated-trading-platform
./scripts/aws/prod_status.sh
./scripts/aws/verify_prod_public.sh

# 3) DNS vs instance IP
dig +short dashboard.hilovivo.com A
```

Then, **if you get a shell on PROD** (Instance Connect or SSM), run the **first minimum set on the instance** (inspection only):

```bash
# On PROD (via Instance Connect or SSM)
df -h /
free -h
systemctl is-active amazon-ssm-agent 2>/dev/null || systemctl is-active snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null || true
systemctl is-active ssh 2>/dev/null || true
systemctl is-active nginx 2>/dev/null || true
systemctl is-active docker 2>/dev/null || true
cd /home/ubuntu/automated-trading-platform 2>/dev/null && docker compose --profile aws ps 2>/dev/null || echo "no compose or dir"
curl -sS -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8002/api/health || echo "curl_fail"
```

---

## 6. Decision Tree

- **Instance state = Stopped**  
  → Start instance (step 5). Wait 2–3 min. Re-check state, prod_status, verify_prod_public.  
  → If API still fails and instance Running → try reboot (step 6A) or restore_ssm_prod.sh (step 6B).

- **Instance state = Running, API = 200**  
  → PROD is reachable. Optional: run SSM checks; if SSM still ConnectionLost, use Instance Connect or SSH for baseline (§7).

- **Instance state = Running, API ≠ 200 (e.g. 000)**  
  → Open Instance Connect access (step 7) and try **EC2 → Connect → EC2 Instance Connect**.  
  → **Instance Connect succeeds** → Run minimum commands on PROD (§5), then full baseline (§7). Fix stack/nginx if needed (AWS_BRINGUP_RUNBOOK, heal_nginx if applicable).  
  → **Instance Connect fails** → Use **EC2 Serial Console** (step 9). Check disk first; free space or resize; start ssh + amazon-ssm-agent; retry Instance Connect / SSM.

- **After reboot, SSM = Online**  
  → Use Session Manager for all further steps; run §7 baseline and fill baseline doc.

- **After reboot, SSM = ConnectionLost**  
  → Run `./scripts/aws/restore_ssm_prod.sh` (or do VPC endpoint SG fix + IAM replace manually per RUNBOOK_SSM_PROD_CONNECTION_LOST).  
  → If still ConnectionLost and you have no SSH: use Serial Console (step 9).

- **Disk full (df -h / shows 100% or near)**  
  → Free space from Serial Console (or existing shell): journalctl vacuum, apt clean, docker system prune. If insufficient, follow PROD_DISK_RESIZE.md (resize EBS, growpart, resize2fs). Then start ssh + SSM agent and retry access.

---

## 7. What To Do Immediately After Access Is Restored

- Run the **exact commands** listed in **docs/ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md** section “Exact commands to run on each instance” (and “Commands to run on each instance”) **on PROD**.
- **Capture and save** all output (timers, unit files, crontab, docker compose ps, health curls, verify.sh exit, log/state paths, journal snippets).
- **Fill in**:
  - **§3 PROD Runtime Inventory** — every row with installed/enabled/running/healthy and evidence.
  - **One-Page Current Health/Recovery Stack: PROD** — table with actual status.
  - **§4 Cross-Environment Comparison** — “what exists only on PROD” and “drift” using LAB baseline already completed.
- **Optionally** run **docs/aws/AWS_LIVE_AUDIT.md** §2 commands and **docs/aws/AWS_BRINGUP_RUNBOOK.md** operator section (diagnostics + bring-up) if you need to bring the app stack up or document listening ports/processes.

---

## 8. Single Safest Next Action

**Recommendation: run the inspection-only commands from your machine (no reboot, no SG change yet).**

1. Confirm **instance state** and **public IP**.  
2. Re-run **prod_status.sh** and **verify_prod_public.sh** to see current API and SSM.  
3. Check **DNS** (dig) vs that IP.  
4. In **EC2 Console**, check **Status checks** and **Security** (SG, IAM role) for i-087953603011543c5.

This gives a clear picture: instance running or not, API reachable or not, DNS aligned or not. From there, the next step is either **start instance**, **reboot**, **open Instance Connect and try browser Connect**, or **go to Serial Console** — without guessing.

---

## Copy-paste: Inspection-only PROD checks (from your machine)

```bash
cd /path/to/automated-trading-platform
export AWS_REGION=ap-southeast-1
export INSTANCE_ID=i-087953603011543c5

# Instance state and IP
aws ec2 describe-instances --region $AWS_REGION --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].{State:State.Name,PublicIp:PublicIpAddress,Sg:SecurityGroups[0].GroupId}' --output table

# API and SSM
./scripts/aws/prod_status.sh
./scripts/aws/verify_prod_public.sh

# DNS
dig +short dashboard.hilovivo.com A

# SSM PingStatus only
aws ssm describe-instance-information --region $AWS_REGION \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].{PingStatus:PingStatus,LastPing:LastPingDateTime}' --output table
```

---

## Copy-paste: Safe recovery actions (when you decide to act)

```bash
cd /path/to/automated-trading-platform
export AWS_REGION=ap-southeast-1
export INSTANCE_ID=i-087953603011543c5

# 1) Reboot PROD (if instance is Running and you want to try restoring SSM)
aws ec2 reboot-instances --region $AWS_REGION --instance-ids $INSTANCE_ID
# Wait 3–5 minutes, then:
./scripts/aws/prod_status.sh

# 2) Or full SSM restore (reboot + EIC + agent restart + VPC endpoints + IAM + logs)
./scripts/aws/restore_ssm_prod.sh

# 3) Open SSH for EC2 Instance Connect (so browser Connect works)
./scripts/aws/open_prod_access.sh

# 4) If instance was stopped: start it
aws ec2 start-instances --region $AWS_REGION --instance-ids $INSTANCE_ID
# Wait 2–3 min, then re-run prod_status.sh and verify_prod_public.sh
```

Then use **EC2 → Instances → atp-rebuild-2026 → Connect → EC2 Instance Connect** (or Session Manager if Online), and run the **minimum on-instance commands** in §5 and the **full baseline commands** in ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md.

---

## What NOT to do yet (avoid making things worse)

- **Do not** change application code, deploy, or run deploy workflows until PROD access and baseline are confirmed.
- **Do not** add new health/recovery automation or timers until the runtime baseline (§3 and one-page PROD stack) is filled.
- **Do not** revoke or tighten security group rules (e.g. remove 22/80/443) until you have a working access path (SSM or Instance Connect or Serial Console).
- **Do not** run **heal.sh**, **heal_nginx**, or **bringup** beyond start/reboot until you have a shell and have run inspection commands; otherwise you may restart services blindly.
- **Do not** assume DNS is correct: verify A record vs current public IP after any start/reboot.
- **Do not** run scripts that modify PROD (e.g. inject_ssh_key, deploy, fix_backend) until you have confirmed access and decided on the next fix step.
