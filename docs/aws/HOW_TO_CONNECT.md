# How to connect to PROD and LAB

Single reference for connecting to **PROD** (dashboard) and **LAB** (OpenClaw).  
**Region:** ap-southeast-1

---

## Quick reference

| Instance | Name | ID | Connect when… |
|----------|------|-----|----------------|
| **PROD** | atp-rebuild-2026 | i-087953603011543c5 | Deploy, nginx, backend. |
| **LAB** | atp-lab-ssm-clean | i-0d82c172235770a0d | Start OpenClaw, fix 504. |

---

## 1. AWS Console (works without SSH/SSM)

Use **EC2 → Instances → select instance → Connect**.

### PROD
1. **EC2** → **Instances** → select **atp-rebuild-2026** (i-087953603011543c5).
2. **Connect** → **EC2 Instance Connect** → **Connect**.
3. Browser terminal opens (no .pem). If it fails, add **inbound SSH (22)** from **My IP** to PROD’s security group (e.g. sg-07f5b0221b7e69efe).  
   See [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md) §5.

### LAB (fix 504 — start OpenClaw)
**LAB has port 22 open** (SG allows SSH). Use the browser so you don’t depend on your network reaching LAB:

1. **EC2** → **Instances** → select **atp-lab-ssm-clean** (i-0d82c172235770a0d).
2. **Connect** → **EC2 Instance Connect** → **Connect** (browser terminal).
3. Run:  
   `cd /home/ubuntu/automated-trading-platform && NONINTERACTIVE=1 sudo bash scripts/openclaw/check_and_start_openclaw.sh`  
   Full steps: [START_OPENCLAW_ON_LAB_CONSOLE.md](../runbooks/START_OPENCLAW_ON_LAB_CONSOLE.md).

---

## 2. Session Manager (SSM) — when PingStatus is Online

From your machine (AWS CLI configured):

```bash
# PROD
aws ssm start-session --target i-087953603011543c5 --region ap-southeast-1

# LAB
aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
```

Check status:

```bash
aws ssm describe-instance-information --region ap-southeast-1 \
  --filters "Key=InstanceIds,Values=i-087953603011543c5,i-0d82c172235770a0d" \
  --query "InstanceInformationList[*].[InstanceId,PingStatus]" --output table
```

If **ConnectionLost**, use **EC2 Instance Connect** (Console) or SSH (if allowed).

---

## 3. SSH (when SG allows port 22 from your IP)

**PROD** (confirm public IP in EC2 console; often 52.220.32.147):

```bash
ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147
# or
ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@dashboard.hilovivo.com
```

**LAB** has a private IP (172.31.3.214); you can’t SSH to it from the internet unless LAB has a public IP and its SG allows 22 from your IP. Prefer **Console → Connect → EC2 Instance Connect** for LAB.

---

## 4. EC2 Instance Connect from CLI (no .pem)

Scripts use this when SSM is down. Pushes a temporary key (60s) then SSH.

**PROD (fix nginx / start nginx):**
```bash
./scripts/openclaw/fix_504_via_eice.sh
```

**LAB (start OpenClaw)** — only if LAB’s SG allows inbound SSH (22) from your IP:
```bash
./scripts/openclaw/start_openclaw_on_lab_via_eice.sh
```

Otherwise use **Console → LAB → Connect → EC2 Instance Connect** and run the one-liner from [START_OPENCLAW_ON_LAB_CONSOLE.md](../runbooks/START_OPENCLAW_ON_LAB_CONSOLE.md).

---

## Summary

| Goal | Preferred method |
|------|-------------------|
| Get a shell on PROD | **Console** → PROD → Connect → EC2 Instance Connect (or SSM if Online, or SSH if SG allows). |
| Get a shell on LAB | **Console** → LAB → Connect → EC2 Instance Connect. |
| Fix 504 (start OpenClaw on LAB) | **Console** → LAB → Connect → EC2 Instance Connect → run the one-liner in [START_OPENCLAW_ON_LAB_CONSOLE.md](../runbooks/START_OPENCLAW_ON_LAB_CONSOLE.md). |
| Fix nginx / proxy on PROD from your machine | `./scripts/openclaw/fix_504_via_eice.sh` (uses EICE to PROD). |

**References:** [INSTANCE_SOURCE_OF_TRUTH.md](../runbooks/INSTANCE_SOURCE_OF_TRUTH.md), [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md), [START_OPENCLAW_ON_LAB_CONSOLE.md](../runbooks/START_OPENCLAW_ON_LAB_CONSOLE.md).
