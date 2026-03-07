# Runbook: Architecture B — PROD and LAB EC2 isolation

**Goal:** Two EC2 instances (PROD and LAB) with real isolation: separate Security Groups, IAM roles, and secrets. SSM-only access where possible; no PROD secrets on LAB.

**Decisión 2026-02-24:** Producción = **atp-rebuild-2026** (i-087953603011543c5). **crypto 2.0** (i-08726dc37133b2454) se ignora; no usar para PROD.

**Region:** ap-southeast-1  
**VPC:** vpc-09930b85e52722581

---

## Reference: Current state

| Role   | Instance name      | Instance ID        | Public IP    | Subnet                  | Instance SG              | IAM role    |
|--------|--------------------|--------------------|--------------|-------------------------|--------------------------|-------------|
| PROD   | atp-rebuild-2026   | i-087953603011543c5 | 52.77.216.100 | subnet-0f4a20184f9106c6c | sg-07f5b0221b7e69efe (launch-wizard-6) | EC2_SSM_Role |
| Other  | crypto 2.0         | i-08726dc37133b2454 | (varies)     | subnet-05dfde4f4da3a8887 | (current SG)             | (current)   |
| Other  | trade_Bot          | i-02a54aef28381374c | (e.g. 13.215.235.23) | (same VPC)   | (current SG)             | (current)   |

PROD candidate = atp-rebuild-2026. LAB = either reuse crypto 2.0 or a new instance (see Section 1).

---

## 1) LAB decision: Reuse "crypto 2.0" vs create new

### 1.1 Decision rubric

| Criterion | Reuse crypto 2.0 as LAB | Create new LAB instance |
|-----------|-------------------------|---------------------------|
| **Current usage** | Repo and GitHub Actions target i-08726dc37133b2454 as the main deploy instance. Reuse implies decommissioning it from production and switching all prod references to i-087953603011543c5. | No change to existing instance roles; PROD and LAB are clearly separate from day one. |
| **Risk** | Instance may have held PROD secrets (atp.env, Telegram, Crypto.com keys). Conversion requires: remove/rotate any PROD creds, overwrite with LAB-scoped/dummy secrets, and ensure no copy remains. One missed secret = LAB has PROD capability. | Clean slate; LAB never receives PROD secrets. |
| **Cost** | No extra instance cost. | One additional EC2 (same size as LAB); order of magnitude similar to PROD. |
| **Cleanup / reversibility** | Must: (1) migrate production workload and scripts to PROD (atp-rebuild-2026), (2) document "crypto 2.0 = LAB only", (3) wipe or replace env on crypto 2.0, (4) attach atp-lab-sg and LAB IAM role. Reversible only by re‑assigning SGs/roles and re‑loading env. | No cleanup of prod references for LAB. New instance can be terminated later if LAB is discontinued; PROD unchanged. |

### 1.2 Recommendation

**Recommendation: Create a new LAB instance.**

- **Isolation:** LAB never has PROD secrets; no risk of leftover credentials.
- **Clarity:** "crypto 2.0" is wired as the current prod target in many scripts and workflows; repurposing it forces a broad script/ID change and ambiguity during transition. A new LAB keeps PROD/LAB boundaries obvious.
- **Cost:** One extra small EC2 is typically low relative to operational safety.

**Reuse** is reasonable only if:
- You are willing to fully decommission production on crypto 2.0 first (move prod to atp-rebuild-2026, then rotate/wipe all secrets on crypto 2.0), and
- You accept the one-time cleanup of replacing instance IDs in scripts and GitHub Actions.

### 1.3 One question before you proceed

**Is "crypto 2.0" (i-08726dc37133b2454) still running production workloads or holding production secrets?**

- **If yes:** Do **not** reuse it as LAB until production has been moved to atp-rebuild-2026 and all secrets on crypto 2.0 have been rotated or removed. Prefer **create new LAB**.
- **If no (already decommissioned or never had real prod):** Reuse is feasible; follow Section 1.4 to convert it into LAB safely.

### 1.4 If reusing crypto 2.0 as LAB — minimum steps

1. **Confirm prod is off** — No live trading or prod traffic on crypto 2.0; prod runs on atp-rebuild-2026.
2. **Rotate or remove all PROD secrets** on crypto 2.0: wipe or overwrite `/opt/atp/atp.env` (and any `.env.aws` or equivalent) so it contains only LAB-scoped/dummy values (see Section 4). Rotate Telegram/Crypto.com/DB creds if they were ever used there.
3. **Replace instance SG** — Remove current SG; attach **atp-lab-sg** (Section 2).
4. **Replace IAM role** — Detach current role; attach **LAB IAM role** (Section 3).
5. **Rename (optional)** — EC2 console: set Name tag to e.g. `atp-lab` for clarity.
6. **Update docs/scripts** — Point LAB-only workflows to i-08726dc37133b2454; ensure prod workflows use i-087953603011543c5.

### 1.5 If creating new LAB — launch in same VPC (Console)

1. **EC2** → **Instances** → **Launch instance**.
2. **Name:** `atp-lab`.
3. **AMI:** Ubuntu Server 22.04 LTS (or same as PROD).
4. **Instance type:** Same as PROD or smaller (e.g. t3.small).
5. **Key pair:** Create new or select existing (optional; SSM does not require it).
6. **Network settings:**
   - **VPC:** vpc-09930b85e52722581.
   - **Subnet:** e.g. subnet-05dfde4f4da3a8887 (ap-southeast-1b) or another in same VPC (avoid same subnet as PROD if you want AZ separation).
   - **Auto-assign public IP:** Enable (or use only private + SSM).
   - **Security group:** Create new → name **atp-lab-sg** (we will create it in Section 2 first; then select it here), or create placeholder and replace in Section 2.
7. **Storage:** Default or match PROD (e.g. 20–30 GB gp3).
8. **Advanced details:**
   - **IAM instance profile:** Select **LAB IAM role** (create in Section 3 first; then attach here or after launch).
9. **Launch**. Note the new instance ID (e.g. **i-xxxxxxxxx**).

**Optional CLI (do not assume CLI is installed):**

```bash
# After atp-lab-sg and LAB IAM role exist (Sections 2 and 3)
aws ec2 run-instances --region ap-southeast-1 \
  --image-id ami-0d2d3a2a3a3a3a3a3a \
  --instance-type t3.small \
  --key-name "your-key" \
  --subnet-id subnet-05dfde4f4da3a8887 \
  --security-group-ids sg-LAB_SG_ID \
  --iam-instance-profile Name=LAB_IAM_ROLE_NAME \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=atp-lab}]'
# Replace ami-id, key-name, sg-LAB_SG_ID, LAB_IAM_ROLE_NAME with actual values.
```

---

## 2) Isolation controls — Security Groups

### 2.1 Create PROD SG: atp-prod-sg

**Console:**

1. **EC2** → **Security Groups** → **Create security group**.
2. **Name:** `atp-prod-sg`. **Description:** PROD EC2 for ATP; SSM only.
3. **VPC:** vpc-09930b85e52722581.
4. **Inbound rules:** Add only if you must allow 80/443 from a load balancer or specific IP; otherwise **no inbound** (SSM uses outbound from instance to SSM endpoints / VPC endpoints).
   - For **SSM-only** (no ALB in front): leave inbound **empty** (Session Manager does not require inbound to the instance).
   - If you need HTTP/HTTPS from internet/ALB: add one rule each as needed, e.g. Type HTTPS, Port 443, Source = ALB SG or your CIDR; Type HTTP, Port 80, Source = same.
5. **Outbound rules:** Option A A1 style (see EGRESS_HARDENING_DESIGN):

| Type        | Protocol | Port | Destination            | Description        |
|-------------|----------|------|------------------------|--------------------|
| HTTPS       | TCP      | 443  | 0.0.0.0/0              | App APIs (Crypto, Telegram, etc.) |
| HTTP        | TCP      | 80   | 169.254.169.254/32     | Instance metadata  |
| Custom TCP   | TCP      | 53   | 0.0.0.0/0 (or VPC DNS) | DNS TCP            |
| Custom UDP   | UDP      | 53   | 0.0.0.0/0 (or VPC DNS) | DNS UDP            |

6. **Create security group.** Note **atp-prod-sg** ID (e.g. sg-xxxxxxxx).

**Optional CLI (create atp-prod-sg):**

```bash
# Create SG (no inbound)
aws ec2 create-security-group --region ap-southeast-1 \
  --group-name atp-prod-sg \
  --description "PROD EC2 for ATP; SSM only" \
  --vpc-id vpc-09930b85e52722581
# Note GroupId (sg-xxxxxxxx). Then add outbound rules (next).

# Add outbound rules (replace sg-xxxxxxxx with atp-prod-sg ID)
aws ec2 authorize-security-group-egress --group-id sg-xxxxxxxx --ip-permissions \
  "[{\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,\"IpRanges\":[{\"CidrIp\":\"0.0.0.0/0\",\"Description\":\"App APIs\"}]},\
   {\"IpProtocol\":\"tcp\",\"FromPort\":80,\"ToPort\":80,\"IpRanges\":[{\"CidrIp\":\"169.254.169.254/32\",\"Description\":\"IMDS\"}]},\
   {\"IpProtocol\":\"tcp\",\"FromPort\":53,\"ToPort\":53,\"IpRanges\":[{\"CidrIp\":\"0.0.0.0/0\",\"Description\":\"DNS TCP\"}]},\
   {\"IpProtocol\":\"udp\",\"FromPort\":53,\"ToPort\":53,\"IpRanges\":[{\"CidrIp\":\"0.0.0.0/0\",\"Description\":\"DNS UDP\"}]}]"
```

### 2.2 Create LAB SG: atp-lab-sg

1. **EC2** → **Security Groups** → **Create security group**.
2. **Name:** `atp-lab-sg`. **Description:** LAB EC2 for ATP experiments; SSM only.
3. **VPC:** vpc-09930b85e52722581.
4. **Inbound rules:** **None** (SSM only).
5. **Outbound rules:** Temporarily broader for installs, but still safe (no need to open risky ports):

| Type        | Protocol | Port | Destination            | Description        |
|-------------|----------|------|------------------------|--------------------|
| HTTPS       | TCP      | 443  | 0.0.0.0/0              | Package installs, APIs |
| HTTP        | TCP      | 80   | 0.0.0.0/0              | Apt/package repos (optional; can restrict later) |
| HTTP        | TCP      | 80   | 169.254.169.254/32     | Instance metadata  |
| Custom TCP   | TCP      | 53   | 0.0.0.0/0 (or VPC DNS) | DNS TCP            |
| Custom UDP   | UDP      | 53   | 0.0.0.0/0 (or VPC DNS) | DNS UDP            |

You can later tighten LAB outbound (e.g. drop HTTP 80 to 0.0.0.0/0) once base installs are done.

6. **Create security group.** Note **atp-lab-sg** ID.

**Optional CLI (create atp-lab-sg):** Same as above with `--group-name atp-lab-sg` and `--description "LAB EC2 for ATP; SSM only"`; add outbound rules including HTTP 80 to 0.0.0.0/0 for Apt if desired.

### 2.3 Exact rules summary (both directions)

**atp-prod-sg:**

| Direction | Type        | Protocol | Port | Source / Destination    | Description        |
|-----------|-------------|----------|------|--------------------------|--------------------|
| Inbound   | —           | —        | —    | —                        | None (SSM only)    |
| Outbound  | HTTPS       | TCP      | 443  | 0.0.0.0/0                | App APIs           |
| Outbound  | HTTP        | TCP      | 80   | 169.254.169.254/32      | IMDS               |
| Outbound  | Custom TCP  | TCP      | 53   | 0.0.0.0/0 or VPC resolver | DNS TCP          |
| Outbound  | Custom UDP  | UDP      | 53   | 0.0.0.0/0 or VPC resolver | DNS UDP          |

**atp-lab-sg:**

| Direction | Type        | Protocol | Port | Source / Destination    | Description        |
|-----------|-------------|----------|------|--------------------------|--------------------|
| Inbound   | —           | —        | —    | —                        | None (SSM only)    |
| Outbound  | HTTPS       | TCP      | 443  | 0.0.0.0/0                | Install/APIs       |
| Outbound  | HTTP        | TCP      | 80   | 0.0.0.0/0                | Apt (optional)     |
| Outbound  | HTTP        | TCP      | 80   | 169.254.169.254/32       | IMDS               |
| Outbound  | Custom TCP  | TCP      | 53   | 0.0.0.0/0 or VPC resolver | DNS TCP          |
| Outbound  | Custom UDP  | UDP      | 53   | 0.0.0.0/0 or VPC resolver | DNS UDP          |

### 2.4 Attach SGs to instances

- **PROD (atp-rebuild-2026):** EC2 → Instances → Select i-087953603011543c5 → Security → Edit → Replace with **atp-prod-sg** (remove launch-wizard-6 or keep as secondary only if you have a reason; prefer single SG atp-prod-sg).
- **LAB (new or crypto 2.0):** Same flow; attach **atp-lab-sg** only.

---

## 3) IAM roles

### 3.1 PROD role — minimum for SSM + required AWS integrations

**Required:**

- **SSM:** So Session Manager and Run Command work (no SSH).
- **Instance metadata:** Already available to instance; no extra IAM.
- **Any AWS integrations used by the app:** e.g. Secrets Manager read, S3 read, CloudWatch Logs — only if the application code actually uses them.

**Managed policies to attach (prefer AWS managed):**

| Policy name (AWS managed)        | Purpose                    |
|----------------------------------|----------------------------|
| **AmazonSSMManagedInstanceCore** | SSM Agent, Session Manager, Run Command |

If the app uses other AWS services, add only what is needed (e.g. **AmazonSecretsManagerReadOnly**, or custom policy scoped to a single S3 bucket). Do **not** attach broad policies (e.g. full S3, full Secrets Manager) unless required.

**Console steps — create/update PROD role:**

1. **IAM** → **Roles** → **Create role**.
2. **Trusted entity:** AWS service → **EC2** → Next.
3. **Permissions:** Add **AmazonSSMManagedInstanceCore** → Next.
4. **Role name:** e.g. `atp-prod-ec2-role` (or keep using **EC2_SSM_Role** if it already has only this policy). Create role.
5. **Attach to PROD instance:** EC2 → Instances → Select i-087953603011543c5 → Actions → Security → Modify IAM role → Select this role → Update.

If **EC2_SSM_Role** already exists and has only `AmazonSSMManagedInstanceCore`, you can keep using it; ensure no extra policies with write or broad read.

### 3.2 LAB role — SSM + optional read-only for experiments

**Required:** SSM (same as PROD).  
**Optional:** Read-only permissions for experiments (e.g. read-only S3, read-only Secrets Manager for non-PROD secrets, read-only CloudWatch). Prefer AWS managed where possible.

**Managed policies to attach:**

| Policy name (AWS managed)        | Purpose                    |
|----------------------------------|----------------------------|
| **AmazonSSMManagedInstanceCore**  | SSM Agent, Session Manager |
| **ReadOnlyAccess** (optional)    | Broad read-only for experiments; use only if you accept read access to all resources in the account. Prefer custom policy with limited scope. |

**Console steps — create LAB role:**

1. **IAM** → **Roles** → **Create role**.
2. **Trusted entity:** AWS service → **EC2** → Next.
3. **Permissions:** Add **AmazonSSMManagedInstanceCore**. Optionally add **ReadOnlyAccess** or a custom read-only policy → Next.
4. **Role name:** `atp-lab-ec2-role` → Create role.
5. **Attach to LAB instance:** EC2 → Instances → Select LAB instance → Actions → Security → Modify IAM role → Select **atp-lab-ec2-role** → Update.

---

## 4) Secrets separation

### 4.1 Secrets inventory (ATP)

From `ops/atp.env.template` and audit docs:

| Secret / env var                     | Used by              | PROD-only | LAB-scoped / dummy |
|-------------------------------------|----------------------|-----------|---------------------|
| POSTGRES_PASSWORD / DATABASE_URL    | db, backend, market-updater | Yes       | LAB: dummy DB or separate LAB DB URL; never PROD URL |
| SECRET_KEY                          | backend (sessions)   | Yes       | LAB: generate new dummy |
| ADMIN_ACTIONS_KEY                   | backend (admin API) | Yes       | LAB: generate new dummy |
| DIAGNOSTICS_API_KEY                 | backend (diagnostics) | Yes     | LAB: generate new dummy |
| TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID, _AWS, _ALERT | backend, telegram-alerts | Yes | LAB: separate bot + chat or dummy; never PROD token/chat |
| EXCHANGE_CUSTOM_API_KEY / EXCHANGE_CUSTOM_API_SECRET | backend, market-updater | Yes | LAB: never PROD keys; dummy or read-only test keys only |
| GRAFANA_ADMIN_USER / GF_SECURITY_ADMIN_PASSWORD | Grafana (optional) | Yes (if prod Grafana) | LAB: separate Grafana or dummy |
| CRYPTO_PROXY_TOKEN (if used)        | backend              | Yes       | LAB: dummy or omit |

**PROD-only:** Must exist only on PROD instance and in PROD secret store; never copied to LAB.  
**LAB-scoped:** Generated or created separately for LAB (dummy values or dedicated LAB bot/chat/DB); no overlap with PROD.

### 4.2 Safe LAB secrets plan

1. **Do not copy** any PROD env file or secrets to LAB.
2. **Generate new values for LAB:**
   - `SECRET_KEY`, `ADMIN_ACTIONS_KEY`, `DIAGNOSTICS_API_KEY`: e.g. `openssl rand -hex 32` (one per var).
   - **Database:** Either a separate LAB database (new RDS or local Postgres in LAB) with its own `POSTGRES_PASSWORD` and `DATABASE_URL`, or dummy placeholders if the LAB stack does not need a real DB.
   - **Telegram:** Create a separate LAB bot (BotFather) and LAB chat/channel; set `TELEGRAM_BOT_TOKEN*` and `TELEGRAM_CHAT_ID*` to those. Do not use PROD bot or PROD chat ID.
   - **Crypto.com:** Do not use PROD API keys. Use test/sandbox keys if exchange provides them, or dummy placeholders and disable live trading (`LIVE_TRADING=false`).
3. **Store on LAB instance:** Single file **/opt/atp/atp.env** (same path as PROD for consistency, different content).
4. **Permissions:** `chown ubuntu:ubuntu /opt/atp/atp.env` and `chmod 600 /opt/atp/atp.env`. Ensure only the app user (e.g. ubuntu or the user running Docker) can read it.

**Optional:** Use AWS Secrets Manager for PROD (and optionally for LAB) and have the instance pull at startup; then LAB secrets are in a separate secret (e.g. `atp/lab/env`) and PROD in `atp/prod/env`. Console steps for that can be added in a follow-up.

---

## 5) Access workflow

### 5.1 Day-to-day connection (SSM)

- **PROD:** `aws ssm start-session --target i-087953603011543c5 --region ap-southeast-1`  
  (Or use Session Manager in EC2 console: Instances → Select atp-rebuild-2026 → Connect → Session Manager.)
- **LAB:** `aws ssm start-session --target <LAB_INSTANCE_ID> --region ap-southeast-1`  
  Replace `<LAB_INSTANCE_ID>` with the LAB instance ID (new or i-08726dc37133b2454 if reused).

No SSH required; no inbound 22. Ensure your IAM user/role has `ssm:StartSession` and the instance has the SSM-managed instance core policy (Section 3).

### 5.2 Cursor / scripts — run safely without relying on your public IP

- **Run scripts locally:** Use AWS CLI (or SDK) to call SSM **Send Command** or **Start Session** from your machine. No need to open inbound firewall to instance; your laptop’s public IP is irrelevant. Example: `aws ssm send-command --instance-ids i-087953603011543c5 --document-name "AWS-RunShellScript" --parameters 'commands=["whoami"]' --region ap-southeast-1`. Use this for one-off commands or automation (e.g. from Cursor terminal or CI).
- **Interactive shell:** Use **Start Session** (above) for interactive work; port forwarding if needed: `aws ssm start-session --target i-087953603011543c5 --document-name AWS-StartPortForwardingSessionToRemoteHost --parameters '{"host":["localhost"],"portNumber":["8002"],"localPortNumber":["8002"]}' --region ap-southeast-1`.
- **Do not** add your home IP to instance SGs for SSH; keep access via SSM only so Cursor (and any script) works from any network.

---

## 6) GO/NO-GO checklist

Before considering Architecture B “done”:

- [ ] **PROD instance:** atp-rebuild-2026 (i-087953603011543c5) has **atp-prod-sg** attached; no launch-wizard-6 (or only atp-prod-sg).
- [ ] **LAB instance:** Either new instance or crypto 2.0; has **atp-lab-sg** only; no PROD secrets on it.
- [ ] **PROD IAM:** Instance profile = role with **AmazonSSMManagedInstanceCore** only (plus minimal extra if required); no broad write.
- [ ] **LAB IAM:** Instance profile = LAB role (SSM + optional read-only).
- [ ] **Secrets:** PROD has /opt/atp/atp.env with PROD-only secrets; LAB has /opt/atp/atp.env with LAB-scoped/dummy only; permissions 600, owner appropriate.
- [ ] **SSM:** Session Manager opens to both PROD and LAB from your account.
- [ ] **Evidence:** Screenshots and command outputs stored (Section 7).

**GO:** All items checked and evidence stored.  
**NO-GO:** Any item unchecked or PROD secrets present on LAB → fix before closing.

---

## 7) Evidence to capture (store in docs/audit)

1. **Security groups**  
   - Screenshot: atp-prod-sg inbound/outbound rules.  
   - Screenshot: atp-lab-sg inbound/outbound rules.

2. **Instances**  
   - Screenshot: EC2 instance list showing PROD and LAB with correct Names and SGs.  
   - Optional CLI:  
     `aws ec2 describe-instances --instance-ids i-087953603011543c5 <LAB_ID> --region ap-southeast-1 --query 'Reservations[*].Instances[*].[InstanceId,Tags[?Key==\`Name\`].Value|[0],SecurityGroups[*].GroupId]' --output table`

3. **IAM**  
   - Screenshot: PROD instance IAM role and attached policies (only SSM + minimal).  
   - Screenshot: LAB instance IAM role and attached policies.

4. **SSM**  
   - Screenshot: Session Manager tab connected to PROD.  
   - Screenshot: Session Manager tab connected to LAB.  
   - Optional: From SSM session on each, `echo "SSM OK"` and `whoami`; save output.

5. **Secrets (no values)**  
   - List of files: e.g. `ls -la /opt/atp/atp.env` from PROD and LAB (permissions only; do not capture content).  
   - Confirm LAB atp.env does not contain PROD tokens (manual check; do not paste secrets into evidence).

Save under `docs/audit/` with names like `ARCH_B_PROD_LAB_EVIDENCE_YYYY-MM-DD.md` or a dedicated subfolder.

---

## 8) Summary

| Item        | PROD (atp-rebuild-2026)     | LAB (new or crypto 2.0)     |
|------------|-----------------------------|-----------------------------|
| SG         | atp-prod-sg (inbound none; outbound 443, 80 IMDS, 53) | atp-lab-sg (inbound none; outbound 443, 80, 53, IMDS) |
| IAM        | SSM + minimal AWS only      | SSM + optional read-only    |
| Secrets    | /opt/atp/atp.env PROD-only  | /opt/atp/atp.env LAB-scoped/dummy only |
| Access     | SSM only                    | SSM only                    |

**Reversibility:** You can detach atp-prod-sg / atp-lab-sg and reattach previous SGs; you can change IAM roles back. Keep a note of previous SG IDs and role names before switching. Do not copy PROD secrets to LAB at any time.

---

## Appendix A: LAB creation (new instance) — Executed path

**Decision:** Create a **new** LAB instance (do not reuse crypto 2.0). Region: ap-southeast-1, VPC: vpc-09930b85e52722581.

### A.1) Networking layout (discovery)

**Subnets in vpc-09930b85e52722581:**

| Subnet ID                 | AZ               | CIDR            | Map public IP | Used by        |
|---------------------------|------------------|-----------------|---------------|----------------|
| subnet-0f4a20184f9106c6c  | ap-southeast-1a  | 172.31.32.0/20  | Yes           | PROD (atp-rebuild-2026) |
| subnet-05dfde4f4da3a8887  | ap-southeast-1b  | 172.31.16.0/20  | Yes           | crypto 2.0     |
| subnet-055b8b41048d648aa  | ap-southeast-1c  | 172.31.0.0/20   | Yes           | (available)    |

**Public vs private:** The VPC has a single **main** route table (rtb-0bf2ec79d5fd2c1c1) with default route **0.0.0.0/0 → Internet Gateway** (igw-049ab34a4d4167422). All three subnets use this (no subnet-specific route tables). So **all subnets are public** (no NAT gateway in this VPC). SSM works from public or private IP; no requirement for a private subnet.

**AWS Console — how to verify:**

1. **Subnets and AZs:** **VPC** → **Subnets** → filter by VPC **vpc-09930b85e52722581**. Note each **Subnet ID**, **Availability Zone**, **CIDR**, and **Auto-assign public IP** (map public IP).
2. **Route table (public vs private):** **VPC** → **Route tables** → select the route table associated with the VPC (e.g. main). **Routes** tab: if you see **0.0.0.0/0** with target **igw-xxx** = public; if target **nat-xxx** = private for that association.
3. **Which subnets use which route table:** In the same **Route tables** → **Subnet associations** (or **Associations** tab) to see if subnets are explicitly associated or use the main table.

**Optional AWS CLI:**

```bash
# List subnets
aws ec2 describe-subnets --filters "Name=vpc-id,Values=vpc-09930b85e52722581" --region ap-southeast-1 \
  --query 'Subnets[*].[SubnetId,AvailabilityZone,CidrBlock,MapPublicIpOnLaunch]' --output table

# Route tables (public = 0.0.0.0/0 -> igw-xxx)
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=vpc-09930b85e52722581" --region ap-southeast-1 \
  --query 'RouteTables[*].{RT:RouteTableId,Main:Associations[?Main==`true`].Main|[0],Routes:Routes[*].[DestinationCidrBlock,GatewayId,NatGatewayId]}' --output json
```

---

**Chosen subnet for LAB:** **subnet-055b8b41048d648aa** (ap-southeast-1c).

---

### A.2) Create LAB security group: atp-lab-sg

**Exact rules:**

| Direction | Type       | Protocol | Port | Source / Destination    | Description        |
|-----------|------------|----------|------|--------------------------|--------------------|
| Inbound   | —          | —        | —    | —                        | None (SSM only)    |
| Outbound  | HTTPS      | TCP      | 443  | 0.0.0.0/0                | APIs, apt over HTTPS |
| Outbound  | HTTP       | TCP      | 80   | 0.0.0.0/0                | Apt bootstrap (can remove after bootstrap) |
| Outbound  | HTTP       | TCP      | 80   | 169.254.169.254/32       | Instance metadata (IMDS) |
| Outbound  | Custom TCP  | TCP      | 53   | 0.0.0.0/0 (or VPC resolver) | DNS TCP          |
| Outbound  | Custom UDP  | UDP      | 53   | 0.0.0.0/0 (or VPC resolver) | DNS UDP          |

**Exact AWS Console steps (a) — Create atp-lab-sg:**

1. Open **EC2** in **ap-southeast-1** → left menu **Network** → **Security Groups**.
2. Click **Create security group**.
3. **Basic details:**
   - **Security group name:** `atp-lab-sg`
   - **Description:** `LAB EC2 for ATP; SSM only.`
   - **VPC:** Select **vpc-09930b85e52722581**.
4. **Inbound rules:** Leave as-is (no rules). Do not add any rule.
5. **Outbound rules:** Click **Remove** on the default rule (All traffic, 0.0.0.0/0). Then click **Add rule** for each row below:
   - **Type:** HTTPS | **Protocol:** TCP | **Port range:** 443 | **Destination:** 0.0.0.0/0 | **Description:** HTTPS
   - **Type:** HTTP  | **Protocol:** TCP | **Port range:** 80  | **Destination:** 0.0.0.0/0 | **Description:** Apt bootstrap
   - **Type:** HTTP  | **Protocol:** TCP | **Port range:** 80  | **Destination:** 169.254.169.254/32 | **Description:** IMDS
   - **Type:** Custom TCP | **Protocol:** TCP | **Port range:** 53 | **Destination:** 0.0.0.0/0 | **Description:** DNS TCP
   - **Type:** Custom UDP | **Protocol:** UDP | **Port range:** 53 | **Destination:** 0.0.0.0/0 | **Description:** DNS UDP
6. Click **Create security group**. Note the **Security group ID** (e.g. sg-xxxxxxxx).

---

### A.3) Create LAB IAM role: atp-lab-ssm-role

**Attach:** **AmazonSSMManagedInstanceCore** only.

**Exact AWS Console steps (b) — Create atp-lab-ssm-role:**

1. Open **IAM** (global) → left menu **Access management** → **Roles**.
2. Click **Create role**.
3. **Trusted entity type:** **AWS service**. Under **Common use cases**, select **EC2** → **Next**.
4. **Add permissions:** In the search box type **AmazonSSMManagedInstanceCore**. Check the box for **AmazonSSMManagedInstanceCore** (description: "Provides minimum permissions for the Amazon SSM Agent"). Do **not** attach any other policy. Click **Next**.
5. **Name, review, and create:**
   - **Role name:** `atp-lab-ssm-role`
   - **Description:** (optional) e.g. `LAB EC2 role for SSM only`
6. Click **Create role**. Attach this role to the instance at launch (step (c)).

**SSM agent on Ubuntu 24.04 LTS:** The official Ubuntu 24.04 AMI includes the SSM agent pre-installed. No extra install needed for Session Manager.

---

### A.4) Launch new LAB instance

**Planned values:**

| Field                  | Value |
|------------------------|--------|
| Name tag               | atp-lab-openclaw |
| Instance type           | t3.small (or t3.micro) |
| AMI                     | Ubuntu 24.04 LTS |
| VPC                     | vpc-09930b85e52722581 |
| Subnet                  | **subnet-055b8b41048d648aa** (ap-southeast-1c) |
| Auto-assign public IP   | Disabled (SSM works without it) |
| Security group          | atp-lab-sg |
| IAM instance profile    | atp-lab-ssm-role |
| Key pair                | **None** (do not attach a key pair) |

**Exact AWS Console steps (c) — Launch atp-lab-openclaw:**

1. **EC2** (region **ap-southeast-1**) → **Instances** → **Launch instance**.
2. **Name and tags:** In **Name**, enter exactly: `atp-lab-openclaw`.
3. **Application and OS Images (AMI):** **Quick Start** → **Ubuntu** → Select **Ubuntu Server 24.04 LTS** (64-bit x86). Do not change to another AMI.
4. **Instance type:** **t3.small** (or **t3.micro** to save cost).
5. **Key pair (login):** Open the dropdown → choose **Proceed without a key pair** (do **not** create or select a key pair).
6. **Network settings:** Click **Edit**.
   - **VPC:** Select **vpc-09930b85e52722581**.
   - **Subnet:** Select **subnet-055b8b41048d648aa** (ap-southeast-1c).
   - **Auto-assign public IP:** **Disable**.
   - **Firewall (security groups):** **Select existing security group** → select **atp-lab-sg** (only). Ensure no other SG is selected.
7. **Storage:** Leave default (e.g. 8 GiB gp3) or set to 20 GiB if you prefer.
8. **Advanced details:** Expand the section. Under **IAM instance profile**, select **atp-lab-ssm-role**. Leave other defaults.
9. Click **Launch instance**. Note the new **Instance ID** (e.g. i-xxxxxxxxx). Wait until **Instance state** = **Running**.

---

### A.5) Validation (SSM only)

1. Wait until **Instance state** = **Running** (and **Status check** = 2/2 checks passed, if you use it).
2. **EC2** → **Instances** → select **atp-lab-openclaw** → **Connect** → **Session Manager** tab → **Connect**.
3. In the Session Manager browser tab, run the following commands **exactly** in order. Paste outputs into `docs/audit/LAB_BOOTSTRAP_EVIDENCE.md` (see Section A.8).

```bash
uname -a
```

**Expected:** One line with Linux, hostname, kernel version, and Ubuntu 24.04 (e.g. `... GNU/Linux ... x86_64 ...`).

```bash
whoami
```

**Expected:** `ubuntu` or `ssm-user`.

```bash
curl -sI https://api.telegram.org | head
```

**Expected:** HTTP headers (e.g. `HTTP/2 200` or `HTTP/1.1 301`); a few lines of headers, then stop (head cuts output).

```bash
getent hosts api.telegram.org
```

**Expected:** One line with an IP address and `api.telegram.org` (e.g. `149.154.167.220 api.telegram.org` or similar).

```bash
curl -s https://api.ipify.org ; echo
```

**Expected:** A single public IPv4 address (the instance’s outbound IP), then a newline.

4. **Confirm SSM remains Online:** In **EC2** → **Instances** → select **atp-lab-openclaw** → **Details** tab, under **Monitoring and troubleshooting** check **Session Manager** — it should show **Online** (or reconnect Session Manager and confirm the session works).

---

### A.6) Break-glass rollback if SSM fails

If Session Manager does not open to the new LAB instance:

1. **IAM:** EC2 → Instance → **Security** → **Modify IAM role** → ensure **atp-lab-ssm-role** is attached. If it was missing, attach it and wait 1–2 minutes.
2. **Security group:** EC2 → Instance → **Security** → **Security groups** → ensure **atp-lab-sg** is attached and outbound allows HTTPS 443 (and 80 if you kept Apt). SSM uses outbound only; no inbound needed.
3. **SSM agent:** If the instance has no IAM role or wrong role, the agent cannot register. Fix IAM first. If you used a custom AMI without SSM agent, use **EC2 Instance Connect** or **Systems Manager Run Command** from another instance that can reach this one (if any), or attach a key and enable SSH temporarily to install the agent.
4. **Safe access recovery:** Do **not** open 0.0.0.0/0 to port 22. To regain access: attach correct IAM role (atp-lab-ssm-role), wait for agent to register (up to 5 min), retry Session Manager. If the instance is unreachable and you must terminate it, do so from the console; no PROD secrets are on it.

---

### A.7) Evidence checklist (LAB creation)

- [ ] **Chosen subnet + AZ:** subnet-055b8b41048d648aa (ap-southeast-1c).
- [ ] **atp-lab-sg:** Created; inbound none; outbound as in table A.2.
- [ ] **atp-lab-ssm-role:** Created; **AmazonSSMManagedInstanceCore** attached.
- [ ] **Instance:** atp-lab-openclaw launched; atp-lab-sg and atp-lab-ssm-role attached; no key pair.
- [ ] **Validation:** Session Manager connected; all five commands run; outputs and SSM Online confirmed.
- [ ] **Evidence file:** `docs/audit/LAB_BOOTSTRAP_EVIDENCE.md` filled with screenshots and command snippets (see A.8).

---

### A.8) Evidence to capture — what to paste into docs/audit

**Screenshots to take and paste (or attach) into `docs/audit/LAB_BOOTSTRAP_EVIDENCE.md`:**

1. **atp-lab-sg** — EC2 → Security Groups → atp-lab-sg: full view showing **Inbound rules** (empty) and **Outbound rules** (HTTPS 443, HTTP 80 to 0.0.0.0/0, HTTP 80 to 169.254.169.254/32, Custom TCP 53, Custom UDP 53).
2. **atp-lab-ssm-role** — IAM → Roles → atp-lab-ssm-role: **Permissions** tab showing **AmazonSSMManagedInstanceCore** attached (and no other policies).
3. **Instance summary** — EC2 → Instances → atp-lab-openclaw selected: **Details** panel showing Name, Instance ID, State (Running), VPC, Subnet (subnet-055b8b41048d648aa), Security group (atp-lab-sg), IAM role (atp-lab-ssm-role).
4. **Session Manager** — EC2 → Instances → atp-lab-openclaw → Connect → Session Manager: browser tab with session open (terminal visible).
5. **SSM Online** — EC2 → Instances → atp-lab-openclaw → **Details** → **Session Manager** line showing **Online** (or a second screenshot of the Connect panel showing Session Manager available).

**Command output snippets to paste into the evidence file:**

- Full output of: `uname -a`
- Full output of: `whoami`
- Full output of: `curl -sI https://api.telegram.org | head`
- Full output of: `getent hosts api.telegram.org`
- Full output of: `curl -s https://api.ipify.org ; echo`

Use the template in **docs/audit/LAB_BOOTSTRAP_EVIDENCE.md** (see below).

---

### A.9) LAB: Host prep (Node 24, pnpm, OpenClaw directory) — run via SSM

**Target:** atp-lab-openclaw. Connect via **EC2** → **Instances** → atp-lab-openclaw → **Connect** → **Session Manager** → **Connect**, then run the following in order.

**SG note:** NodeSource and apt need **outbound 443 and 80**. atp-lab-sg already allows both. When you have finished installing everything (Node, pnpm, and later OpenClaw deps), remove the outbound rule **HTTP 80 → 0.0.0.0/0** from **atp-lab-sg** (keep HTTP 80 → 169.254.169.254/32 for IMDS). See end of this section.

---

#### Step 1 — Preparar el host

```bash
cd ~
sudo apt-get update -y
sudo apt-get install -y git ca-certificates curl unzip
```

---

#### Step 2 — Instalar Node.js 24 (recomendado para OpenClaw)

```bash
cd ~
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
sudo apt-get install -y nodejs
node -v
npm -v
```

Expected: `node -v` shows v24.x.x; `npm -v` shows 10.x or similar.

---

#### Step 3 — Instalar pnpm

```bash
sudo npm install -g pnpm
pnpm -v
```

Expected: `pnpm -v` shows a version (e.g. 9.x or 10.x).

---

#### Step 4 — Crear carpeta de trabajo para OpenClaw

```bash
mkdir -p ~/openclaw
cd ~/openclaw
```

---

**Cuando termines los pasos 1–3:** Pega en el chat solo la salida de:

- `node -v`
- `pnpm -v`

Siguiente paso: clonar e instalar OpenClaw en `~/openclaw` (runbook en sección "LAB: OpenClaw install (no Docker)" cuando tengas la URL del repo y el comando de entrada).

---

**Después de instalar todo (Node + pnpm + OpenClaw deps): quitar outbound 80 a internet**

1. **EC2** → **Security Groups** → **atp-lab-sg** → **Outbound rules** → **Edit**.
2. **Eliminar** la regla: Type HTTP, Port 80, Destination **0.0.0.0/0** (Apt bootstrap).
3. **Mantener** la regla: Type HTTP, Port 80, Destination **169.254.169.254/32** (IMDS).
4. **Save**.
