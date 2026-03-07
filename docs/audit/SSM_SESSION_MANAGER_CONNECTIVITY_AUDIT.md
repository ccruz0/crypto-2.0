# SSM Session Manager Connectivity Audit

**Symptoms:** SSM Agent Ping Online, Session Manager Not connected  
**Environment:** Ubuntu 24.04, ap-southeast-1, atp-lab-ssm-role  
**Date:** 2025-02-21  

**Key insight:** Agent Ping Online = control plane (ssm + ec2messages) works. Session Manager fail = data plane (ssmmessages) or user-side permissions/connectivity fails.

---

## Findings (ranked by likelihood)

### 1. **IAM — Connector (your user/role) lacks ssm:StartSession**
The instance role (`atp-lab-ssm-role`) allows the agent to register. The **user/role starting the session** needs `ssm:StartSession` (and optionally `iam:PassRole` if using a custom session role). If the connector lacks this, Session Manager fails even though the instance is Online.

### 2. **VPC endpoints — ssmmessages unreachable (if using VPC endpoints)**
If you use VPC Interface Endpoints for SSM:
- Endpoint SG must allow **inbound TCP 443 from the instance SG** for all three endpoints.
- ssmmessages is the data plane; ssm + ec2messages handle registration (hence Ping Online). Misconfigured or missing ssmmessages endpoint → sessions fail.

### 3. **Security group — outbound 443 blocked or too restrictive**
Instance must reach `*.ssm.ap-southeast-1.amazonaws.com`, `*.ec2messages.ap-southeast-1.amazonaws.com`, `*.ssmmessages.ap-southeast-1.amazonaws.com` on 443. If outbound 443 is limited to specific CIDRs that don’t cover SSM endpoints, sessions fail. (Ping Online suggests 443 works, but partial failures are possible if endpoints differ.)

### 4. **NACL — blocks return traffic (stateless rules)**
NACLs are stateless. If you allow outbound 443 but don’t allow inbound ephemeral (1024–65535) from the SSM endpoint IPs, return traffic is dropped and the session can’t establish.

### 5. **IMDSv2 — instance requires IMDSv2, agent can’t get token**
If the instance enforces IMDSv2 (metadata options) and the agent can’t obtain a token (e.g. blocked by SG/NACL to 169.254.169.254), the agent may fail to obtain credentials and the session can stall. Ping Online suggests IMDS works for registration, but IMDSv2 misconfig can affect some flows.

### 6. **Session logging / KMS — key policy blocks SSM**
If Session Manager preferences use S3/KMS for session logging and the KMS key policy doesn’t allow SSM to use it, the session may fail. Check **SSM → Session Manager → Preferences**.

### 7. **Time sync — clock skew breaks TLS**
If instance time is off (e.g. NTP blocked), TLS to SSM endpoints can fail. Registration might succeed initially; session negotiation can then fail.

### 8. **Instance profile — role not actually attached**
EC2 console can show a cached role. Verify via instance metadata (from another session/EC2 Instance Connect) that the instance profile is attached and correct.

### 9. **IAM trust — EC2 service principal missing**
`atp-lab-ssm-role` must have a trust policy allowing `ec2.amazonaws.com` to assume it. Without this, the instance can’t use the role.

### 10. **AWS Organizations SCP — blocks ssm:StartSession**
An SCP on the OU can deny `ssm:StartSession` or related actions. Connector IAM identity must not be subject to such a denial.

### 11. **SSM agent — snap/systemd misbehavior or crashes**
Agent runs but fails during session handshake. Check agent logs for errors during connection attempts.

### 12. **VPC DNS — resolution to wrong/blocked targets**
If `ssmmessages.ap-southeast-1.amazonaws.com` resolves incorrectly (e.g. via Private DNS to unreachable endpoint IPs), sessions fail. VPC DNS must be enabled; resolution must reach reachable endpoints.

---

## Evidence needed

| # | Item | Where to check |
|---|------|----------------|
| 1 | Connector IAM permissions | IAM → Users/Roles → Policies: ssm:StartSession, ssm:DescribeSessions, ssm:TerminateSession |
| 2 | Instance IAM role attachment | EC2 → Instance → Security tab → IAM role |
| 3 | Instance role trust policy | IAM → Roles → atp-lab-ssm-role → Trust relationships |
| 4 | Instance role permissions | IAM → Roles → atp-lab-ssm-role → Permissions → AmazonSSMManagedInstanceCore |
| 5 | Instance SG outbound rules | EC2 → Security Groups → instance SG → Outbound |
| 6 | Subnet NACL rules | VPC → Network ACLs → subnet’s NACL → Inbound/Outbound |
| 7 | VPC endpoints (if used) | VPC → Endpoints → filter by ssm, ssmmessages, ec2messages |
| 8 | Endpoint SGs (if used) | Each endpoint → Security group → Inbound 443 from instance SG |
| 9 | Session Manager prefs | SSM → Session Manager → Preferences (S3/KMS logging) |
| 10 | Instance metadata options | EC2 → Instance → Actions → Instance settings → Edit instance metadata options |
| 11 | SCPs | AWS Organizations → Policies (if org present) |

---

## Commands to run (Ubuntu, on instance if you can reach it)

```bash
# --- 1. SSM agent status ---
sudo systemctl status snap.amazon-ssm-agent.amazon-ssm-agent.service
# or if systemd (older): sudo systemctl status amazon-ssm-agent

# --- 2. SSM agent logs (last 50 lines) ---
sudo journalctl -u snap.amazon-ssm-agent.amazon-ssm-agent.service -n 50 --no-pager
# or: sudo journalctl -u amazon-ssm-agent -n 50 --no-pager

# --- 3. Agent log file (snap) ---
sudo tail -100 /var/snap/amazon-ssm-agent/current/logs/amazon-ssm-agent.log 2>/dev/null || \
sudo tail -100 /var/log/amazon/ssm/amazon-ssm-agent.log 2>/dev/null

# --- 4. IMDSv2 + instance metadata ---
TOKEN=$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" -w "\n%{http_code}" 2>/dev/null | tail -1)
echo "IMDSv2 token HTTP: $TOKEN"
curl -sS -H "X-aws-ec2-metadata-token: $(curl -sS -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")" \
  http://169.254.169.254/latest/meta-data/iam/security-credentials/ 2>/dev/null || echo "No credentials"

# --- 5. DNS resolution for SSM ---
getent hosts ssm.ap-southeast-1.amazonaws.com
getent hosts ec2messages.ap-southeast-1.amazonaws.com
getent hosts ssmmessages.ap-southeast-1.amazonaws.com

# --- 6. Time sync ---
timedatectl status
curl -sI https://ssm.ap-southeast-1.amazonaws.com 2>&1 | head -5

# --- 7. Outbound connectivity to SSM (TLS) ---
curl -sS -m 5 -o /dev/null -w "%{http_code}\n" https://ssm.ap-southeast-1.amazonaws.com/ 2>/dev/null || echo "curl failed"
```

If you cannot reach the instance via SSM, run **4–7** via EC2 Instance Connect (if available) or from another instance in the same VPC/subnet.

---

## Fix steps

### IAM — Connector permissions (your user/role)

**Console:** IAM → Users (or Roles) → your identity → Add permissions → Attach policies  
- Attach `AmazonSSMFullAccess` (for quick fix) **or**
- Create inline policy:
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "ssm:StartSession",
          "ssm:DescribeSessions",
          "ssm:DescribeSessionProperties",
          "ssm:GetConnectionStatus",
          "ssm:TerminateSession"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": "ec2:DescribeInstanceStatus",
        "Resource": "*"
      }
    ]
  }
  ```

**CLI:**
```bash
# Attach managed policy
aws iam attach-user-policy --user-name YOUR_USER --policy-arn arn:aws:iam::aws:policy/AmazonSSMFullAccess
# or for role:
aws iam attach-role-policy --role-name YOUR_ROLE --policy-arn arn:aws:iam::aws:policy/AmazonSSMFullAccess
```

### IAM — Instance role trust + permissions

**Console:** IAM → Roles → atp-lab-ssm-role  
- **Trust relationships** → Edit → ensure:
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": { "Service": "ec2.amazonaws.com" },
        "Action": "sts:AssumeRole"
      }
    ]
  }
  ```
- **Permissions** → Attach `AmazonSSMManagedInstanceCore`

**CLI:**
```bash
aws iam attach-role-policy --role-name atp-lab-ssm-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
```

### Instance profile attachment

**Console:** EC2 → Instances → instance → Actions → Security → Modify IAM role → select `atp-lab-ssm-role`  
**CLI:**
```bash
aws ec2 associate-iam-instance-profile \
  --instance-id i-XXXXXXXXX \
  --iam-instance-profile Name=atp-lab-ssm-role
```
Wait 1–2 minutes after attach for agent to re-register.

### Security group — instance outbound

**Console:** EC2 → Security Groups → instance SG → Edit outbound  
Ensure:
- HTTPS TCP 443 → 0.0.0.0/0 (or VPC CIDR if using endpoints)
- HTTP TCP 80 → 169.254.169.254/32 (IMDS)
- Custom TCP 53, UDP 53 → 0.0.0.0/0 or VPC DNS resolver

**Rollback:** Restore previous outbound rules if this change broke other access.

### VPC endpoints — endpoint SG (if using endpoints)

**Console:** VPC → Endpoints → each of vpce-ssm, vpce-ssmmessages, vpce-ec2messages  
- Select endpoint → Security group → Edit inbound  
- Add: Type HTTPS, Port 443, Source: instance SG (e.g. sg-07f5b0221b7e69efe or atp-lab-sg)

**Rollback:** Disable Private DNS on all three endpoints (VPC → Endpoints → Edit) so SSM uses public endpoints; instance needs outbound 443 to 0.0.0.0/0.

### NACL — allow ephemeral return traffic

**Console:** VPC → Network ACLs → NACL associated with instance subnet  
- **Inbound:** Allow TCP 1024–65535 from 0.0.0.0/0 (or VPC CIDR) — for return traffic  
- **Outbound:** Allow TCP 443 to 0.0.0.0/0; allow ephemeral if required  
Ensure no deny rule overrides these.

**Rollback:** Revert NACL to previous rules.

### IMDSv2 — allow metadata access

**Console:** EC2 → Instance → Actions → Instance settings → Edit instance metadata options  
- Ensure HTTP endpoint = Enabled  
- If requiring IMDSv2, ensure instance SG allows outbound HTTP 80 to 169.254.169.254/32  

**Rollback:** Set metadata options back to previous values.

### Session logging / KMS

**Console:** SSM → Session Manager → Preferences  
- If S3/KMS logging is enabled and sessions fail: either disable logging temporarily **or** fix KMS key policy to allow `ssm.amazonaws.com` and your account.

**Rollback:** Disable session logging or switch to default (no custom KMS).

### SSM agent restart

```bash
sudo systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent.service
# or: sudo systemctl restart amazon-ssm-agent
```
Wait 1–2 minutes, retry Session Manager.

### Time sync

```bash
sudo timedatectl set-ntp true
# or: sudo systemctl start systemd-timesyncd
```

---

## Rollback summary

| Change | Rollback |
|--------|----------|
| IAM policy on connector | Detach policy; re-attach original |
| Instance role | Modify IAM role back to previous |
| SG outbound | Restore previous rules |
| VPC endpoint SG | Revert inbound rules |
| VPC endpoints + Private DNS | Disable Private DNS on all three endpoints |
| NACL | Restore previous rules |
| Session logging/KMS | Disable logging or revert KMS key policy |

---

## Quick validation after fixes

1. EC2 → Instances → Select instance → Connect → Session Manager → Connect.  
2. In session: `echo "SSM OK" && whoami`  
3. Confirm Session Manager status shows Online and sessions connect reliably.
