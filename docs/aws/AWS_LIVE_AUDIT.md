# AWS Live Instance Audit

**Date:** 2026-02-22  
**Region:** ap-southeast-1  
**Scope:** Running EC2 instances only. No infrastructure changes.

---

## 1. Running Instances Summary

### Command used

```bash
aws ec2 describe-instances \
  --region ap-southeast-1 \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[*].Instances[*].[InstanceId,Tags[?Key==`Name`].Value|[0],InstanceType,PrivateIpAddress,PublicIpAddress]' \
  --output table
```

### Result (audit run)

| Instance ID            | Name tag           | Instance type | Private IP     | Public IP     |
|------------------------|--------------------|---------------|----------------|---------------|
| i-087953603011543c5    | atp-rebuild-2026   | t3.small      | 172.31.32.169  | 52.77.216.100 |
| i-0d82c172235770a0d   | atp-lab-ssm-clean  | t2.micro      | 172.31.3.214   | None          |

**Summary:**

- **2** running instances.
- **Production** (atp-rebuild-2026): has public IP; t3.small.
- **Lab** (atp-lab-ssm-clean): no public IP; t2.micro; matches “lab may have no public IP” in architecture.

---

## 2. Instance: atp-rebuild-2026

**Instance ID:** i-087953603011543c5  
**Intended role:** Production (live trading, alerts, Telegram).

### SSM status at audit time

- **PingStatus:** ConnectionLost  
- **Run Command:** Send-command was **Undeliverable** (agent not reachable for this audit run).  
- Runtime checks below were **not** executed on this instance during the audit.

### Commands to run manually (via SSM Session Manager when instance is Online)

Connect via **EC2 → Instances → atp-rebuild-2026 → Connect → Session Manager**, then run:

```bash
# 1) Docker containers
docker ps

# 2) Docker Compose services (aws profile)
cd /home/ubuntu/crypto-2.0
docker compose --profile aws ps

# 3) Listening ports
sudo ss -tulpn

# 4) Running systemd services (sample)
systemctl list-units --type=service --state=running

# 5) Trading-related processes
ps aux | grep -E "signal|trade|scheduler|exchange|gunicorn|market" | grep -v grep
```

### Expected (from docs/aws/AWS_ARCHITECTURE.md)

- **Services:** backend-aws, frontend-aws, market-updater-aws, db, prometheus, grafana, alertmanager, telegram-alerts, node-exporter, cadvisor.
- **Trading:** Enabled (TRADING_ENABLED, RUN_TELEGRAM).
- **Ports:** 8002, 3000, 5432 (internal), 9090, 3001, 9093, 9100, 8080 bound to 127.0.0.1 or Docker network only.

### Assessment (without live output)

- **Role:** Documented as production.
- **Actual behavior:** Not verified this run (SSM ConnectionLost).
- **Recommendation:** When SSM is Online, re-run the commands above and update this section with output.

---

## 3. Instance: atp-lab-ssm-clean

**Instance ID:** i-0d82c172235770a0d  
**Intended role:** Lab (experiments, testing).

### SSM status at audit time

- **PingStatus:** Online  
- **Run Command:** Success.

### Output from audit commands

**Docker containers:** None (no output after `docker ps`).

**Docker Compose:** No services (no project or no `docker compose --profile aws` stack running).

**Listening ports (relevant):**

- **22 (sshd):** Listening on 0.0.0.0 and :: (SSH daemon running).
- **53 (systemd-resolved):** 127.0.0.53, 127.0.0.54.
- No 8002, 3000, 5432, 9090, etc. — no ATP stack listening.

**Running systemd units (sample):**  
snap.amazon-ssm-agent.amazon-ssm-agent.service, ssh.service, chrony, systemd-resolved, etc. No Docker-related units in the truncated list.

**Trading-related processes:** None (only unrelated process matched the grep pattern).

### Interpretation

- **Services running:** None of the ATP stack (no backend, frontend, db, observability).
- **Trading:** Not running (no trading processes).
- **Monitoring stack:** Not running.
- **Match to intended role:** Lab is for experiments; a clean instance with no ATP stack is acceptable. SSM and SSH (sshd) are present; SSH is still blocked at security group (no inbound rules).

---

## 4. Documentation vs Reality

Source: **docs/aws/AWS_ARCHITECTURE.md**.

**Expected per environment:**

- **Production (atp-rebuild-2026):** Full Docker Compose `aws` profile (backend-aws, frontend-aws, market-updater-aws, db, prometheus, grafana, alertmanager, telegram-alerts, node-exporter, cadvisor). Trading and Telegram enabled. Access via SSM (and optionally SSH fallback).
- **Lab (atp-lab-ssm-clean):** Experiments, testing; may have no public IP. Same IAM/SSM pattern; no requirement to run full production stack.
- **Separation:** PROD = live trading/alerts; LAB = non-production only. Different security groups, same or distinct IAM role (EC2_SSM_Role or atp-lab-ssm-role).
- **Security:** SSM-first; minimal inbound; outbound HTTPS 443, IMDS, DNS.

| Instance            | Expected role | Actual behavior (this audit)                    | Conformant | Notes |
|---------------------|---------------|--------------------------------------------------|------------|--------|
| atp-rebuild-2026    | Production    | Not verified (SSM ConnectionLost)                | ⚠ Partial  | Re-run Section 2 commands when SSM is Online. |
| atp-lab-ssm-clean   | Lab           | No ATP stack; SSM Online; no public IP; no trading | ✅ Conformant | Clean lab host; matches “experiments, testing”. |

---

## 5. Security Assessment

### IAM

| Instance            | Instance profile      | Expected     | Match |
|---------------------|-----------------------|-------------|--------|
| atp-rebuild-2026    | EC2_SSM_Role          | EC2_SSM_Role | ✅    |
| atp-lab-ssm-clean   | EC2_SSM_Role          | EC2_SSM_Role or atp-lab-ssm-role | ✅ |

### Security groups (inbound)

| Instance            | Security group        | Inbound rules |
|---------------------|-----------------------|----------------|
| atp-rebuild-2026    | sg-07f5b0221b7e69efe (launch-wizard-6) | None |
| atp-lab-ssm-clean   | sg-021aefb689b9d3c0e (atp-lab-sg2)     | None |

- **Port 22:** Not open by SG (no inbound rules). SSHD is running on lab instance but cannot be reached from internet; aligns with SSM-first model.
- **Public IPs:** Only PROD has public IP (52.77.216.100). Lab has none — good for lab.
- **SSM:** PROD = ConnectionLost at audit time; LAB = Online. PROD may need network/agent check (see docs/audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md).
- **Unnecessary exposure:** No extra inbound rules; no unexpected exposure identified from this audit.

### Summary

- **SSM-first:** Both instances have no inbound SG rules; access intended via SSM. Lab has SSHD listening but not reachable from internet.
- **Production risk:** PROD SSM ConnectionLost prevents remote verification of services and config; recommend resolving SSM connectivity and re-running audit commands.

---

## 6. Risk Summary

| Instance            | Classification      | Reason |
|---------------------|--------------------|--------|
| atp-rebuild-2026    | **Needs verification** | SSM ConnectionLost; could not confirm running services and that only intended stack is active. Resolve SSM, then re-run Section 2 commands. |
| atp-lab-ssm-clean   | **Lab OK**          | No ATP stack, no trading, no public IP, SSM Online, EC2_SSM_Role, no inbound. Matches documented lab role. |

**Overall:** Lab is correctly separated and conformant. Production could not be fully audited this run; no critical risk identified from metadata (IAM, SGs, public IP), but runtime state is unverified until SSM is Online and commands are re-run.

---

## Appendix: AWS CLI reference

```bash
# List running instances
aws ec2 describe-instances --region ap-southeast-1 \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[*].Instances[*].[InstanceId,Tags[?Key==`Name`].Value|[0],InstanceType,PrivateIpAddress,PublicIpAddress]' \
  --output table

# Instance details (IAM, security groups)
aws ec2 describe-instances --region ap-southeast-1 \
  --instance-ids i-087953603011543c5 i-0d82c172235770a0d \
  --query 'Reservations[*].Instances[*].{InstanceId:InstanceId,Name:Tags[?Key==`Name`]|[0].Value,IamInstanceProfile:IamInstanceProfile.Arn,SecurityGroups:SecurityGroups[*].GroupId}' \
  --output json

# SSM agent status
aws ssm describe-instance-information --region ap-southeast-1 \
  --filters "Key=InstanceIds,Values=i-087953603011543c5,i-0d82c172235770a0d" \
  --query 'InstanceInformationList[*].{InstanceId:InstanceId,PingStatus:PingStatus}' \
  --output table

# Inbound rules for instance SGs
aws ec2 describe-security-groups --region ap-southeast-1 \
  --group-ids sg-07f5b0221b7e69efe sg-021aefb689b9d3c0e \
  --query 'SecurityGroups[*].{GroupId:GroupId,GroupName:GroupName,Inbound:IpPermissions}' \
  --output json
```

---

*Audit performed without modifying any infrastructure. Re-run Section 2 commands on atp-rebuild-2026 when SSM is Online to complete production verification.*
