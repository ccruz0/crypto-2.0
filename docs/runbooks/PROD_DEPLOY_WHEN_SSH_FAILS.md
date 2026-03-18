# Runbook: Deploy Production When SSH Times Out

When **SSH** or **ping** to the production server times out, you can still deploy and operate via **Session Manager (SSM)**. This runbook explains how to diagnose reachability and deploy without SSH.

**PROD instance:** atp-rebuild-2026 — `i-087953603011543c5` (region: `ap-southeast-1`).

---

## 1. If SSH times out and ping fails

**First step:** run the reachability script (uses existing AWS CLI config; no secrets to paste):

```bash
./scripts/aws/prod_reachability.sh
```

Optional: pass the API base URL for the health check:

```bash
./scripts/aws/prod_reachability.sh https://dashboard.hilovivo.com
```

The script reports:

- **Instance state** — running / stopped / etc.
- **Public IP** (if any) — may change on stop/start if no Elastic IP.
- **SSM PingStatus** — Online = Session Manager works; ConnectionLost = see [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](../aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md).
- **Security group** — whether SSH (port 22) is allowed.
- **Public API** — HTTP status of `/api/health`.
- **Recommendation** — use SSM vs try SSH, and next steps.

**Likely root causes of SSH/ping timeout:**

| Cause | What to check |
|-------|----------------|
| Instance stopped or unhealthy | `prod_reachability.sh` → instance state; start in EC2 console if needed. |
| Public IP changed or missing | No Elastic IP → IP changes on stop/start. Check EC2 console → Public IPv4. |
| Instance in private subnet | No public IP; use SSM or VPN. |
| Security group blocks SSH/ICMP | `prod_reachability.sh` shows if SG allows port 22; add your IP if needed. |
| NACL / route table | Less common; check VPC routing and NACLs. |
| SSM intended as primary | SSH may be intentionally restricted; use Session Manager. |

For more SSH-specific causes (wrong IP, SG, fail2ban, etc.), see [EC2_SSH_TIMEOUT_DEBUG.md](EC2_SSH_TIMEOUT_DEBUG.md).

---

## 2. Deploy via Session Manager (no SSH)

When **SSM PingStatus is Online**, deploy with:

```bash
./scripts/deploy_production_via_ssm.sh
```

This script:

- Verifies SSM is Online; exits with instructions if not.
- Runs on the server: `git pull origin main`, optional rebuild of `backend-aws`, `docker compose --profile aws up -d backend-aws`, and a local health check.

**Faster deploy (pull + restart only, no rebuild):**

```bash
SKIP_REBUILD=1 ./scripts/deploy_production_via_ssm.sh
```

**Requirements:** AWS CLI configured (e.g. profile or env); no SSH key or secrets needed in the script.

**After deploy:** Verify the public API:

```bash
curl -s -o /dev/null -w '%{http_code}' https://dashboard.hilovivo.com/api/health
```

---

## 3. When is SSH optional vs required?

| Situation | Prefer |
|-----------|--------|
| SSM PingStatus **Online** | **Session Manager** for deploy and shell. SSH is optional. |
| SSM **ConnectionLost** | Fix SSM first (see [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](../aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md)); or use EC2 Instance Connect if available. SSH may be needed for key injection or if SSM cannot be restored. |
| Need to paste keys / one-off file copy | SSH or SCP can be convenient; if SSH is unavailable, use SSM `send-command` or Session Manager + upload via AWS CLI/S3. |

**Recommendation:** Treat **Session Manager as the primary access path** when SSM is Online. Use `deploy_production_via_ssm.sh` for production deploys so they work even when SSH is blocked or times out.

---

## 4. Verify prod is reachable and manageable

- **One-command diagnostic:**  
  `./scripts/aws/prod_reachability.sh`  
  Answers: instance running? public IP? SSM online? SG allows SSH? API up?

- **API + SSM status (existing):**  
  `./scripts/aws/prod_status.sh`  
  Quick API health and SSM PingStatus.

- **Public API health:**  
  `curl -s -o /dev/null -w '%{http_code}' https://dashboard.hilovivo.com/api/health`  
  Expect `200`.

---

## 5. After deploy: verify scheduler

After deploying via SSM, give the new scheduler logic **10–15 minutes** so a few cycles can run.

**Watch backend logs (Session Manager, then on server):**

```bash
aws ssm start-session --target i-087953603011543c5 --region ap-southeast-1
```

On the server:

```bash
cd /home/ubuntu/automated-trading-platform
docker compose --profile aws logs -f backend-aws
```

**Look for:** `scheduler_loop_started`, `scheduler_cycle_completed`, `scheduler_heartbeat_updated`. If an incident was active: at most **one** inactivity alert, then suppression, then **one** recovery when healthy.

**Fast check (same SSM session):** confirm heartbeats are advancing:

```bash
cd /home/ubuntu/automated-trading-platform
grep -E "scheduler_loop_started|scheduler_cycle_completed|scheduler_heartbeat_updated|scheduler_inactivity_alert_suppressed|scheduler_recovered" logs/agent_activity.jsonl 2>/dev/null | tail -50
```

**Success:** repeated Telegram scheduler alerts for the same incident stop.

---

## 6. Summary — exact commands

| Goal | Command |
|------|--------|
| Diagnose instance / SSM / SSH / API | `./scripts/aws/prod_reachability.sh` |
| Deploy production without SSH (SSM Online) | `./scripts/deploy_production_via_ssm.sh` |
| Deploy without rebuild (faster) | `SKIP_REBUILD=1 ./scripts/deploy_production_via_ssm.sh` |
| Check API + SSM only | `./scripts/aws/prod_status.sh` |
| Shell on PROD (no SSH) | `aws ssm start-session --target i-087953603011543c5 --region ap-southeast-1` |

**Files added for this workflow:**

- `scripts/aws/prod_reachability.sh` — reachability and recommendation.
- `scripts/deploy_production_via_ssm.sh` — deploy via SSM (git pull, optional build, restart backend-aws).

**See also:** [AWS_PROD_QUICK_REFERENCE.md](../aws/AWS_PROD_QUICK_REFERENCE.md), [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](../aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md), [EC2_SSH_TIMEOUT_DEBUG.md](EC2_SSH_TIMEOUT_DEBUG.md).
