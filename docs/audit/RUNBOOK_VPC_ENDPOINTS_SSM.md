# Runbook: VPC Interface Endpoints for SSM (Option B)

**Goal:** Add VPC Interface Endpoints (PrivateLink) for AWS Systems Manager so Session Manager works without public internet egress.

**Context:**
- **Region:** ap-southeast-1
- **Instance:** i-087953603011543c5 (private IP 172.31.32.169)
- **VPC:** vpc-09930b85e52722581
- **Instance subnet:** subnet-0f4a20184f9106c6c (ap-southeast-1a)
- **Instance security group:** sg-07f5b0221b7e69efe (launch-wizard-6)
- SSH inbound closed; access via SSM. Egress restricted (Option A A1).

---

## 1) VPC, subnets, and route situation (reference)

### 1.1 Current layout (discovered)

| Item | Value |
|------|--------|
| VPC | vpc-09930b85e52722581 |
| Instance subnet | subnet-0f4a20184f9106c6c (ap-southeast-1a, 172.31.32.0/20) |
| Other subnets (same VPC) | subnet-05dfde4f4da3a8887 (ap-southeast-1b), subnet-055b8b41048d648aa (ap-southeast-1c) |
| Main route table | rtb-0bf2ec79d5fd2c1c1; default route 0.0.0.0/0 → Internet Gateway |
| VPC DNS | enableDnsSupport=true, enableDnsHostnames=true (required for Private DNS on endpoints) |

**Implication:** Instance has outbound via IGW. After endpoints are created and Private DNS is enabled, SSM traffic will go to endpoint ENIs in the VPC (no internet).

### 1.2 AWS Console click-path to locate them

1. **EC2** → **Instances** → select **i-087953603011543c5**.
2. **Details** tab → note **VPC ID**, **Subnet ID**, **Private IPv4 address**.
3. **Security** tab → note **Security group(s)**.
4. **VPC** (left menu) → **Your VPCs** → select the VPC → **Subnets** (lower section) or **Subnets** in left menu filtered by this VPC.
5. **VPC** → **Route tables** → select the route table associated with the subnet → **Routes** tab to see 0.0.0.0/0 → igw-xxx.
6. **VPC** → **Your VPCs** → select VPC → **Actions** → **Edit VPC settings** → confirm **DNS resolution** and **DNS hostnames** are enabled.

### 1.3 Optional AWS CLI (same info)

```bash
# Instance network
aws ec2 describe-instances --instance-ids i-087953603011543c5 --region ap-southeast-1 \
  --query 'Reservations[0].Instances[0].{VpcId:VpcId,SubnetId:SubnetId,PrivateIp:PrivateIpAddress,SecurityGroups:SecurityGroups}'

# Subnets in VPC
aws ec2 describe-subnets --filters "Name=vpc-id,Values=vpc-09930b85e52722581" --region ap-southeast-1 \
  --query 'Subnets[*].[SubnetId,AvailabilityZone,CidrBlock]' --output table

# VPC DNS
aws ec2 describe-vpc-attribute --vpc-id vpc-09930b85e52722581 --attribute enableDnsHostnames --region ap-southeast-1
aws ec2 describe-vpc-attribute --vpc-id vpc-09930b85e52722581 --attribute enableDnsSupport --region ap-southeast-1
```

---

## 2) Required Interface VPC Endpoints for SSM

Create **three** Interface (PrivateLink) endpoints in region **ap-southeast-1**:

| Endpoint name (tag) | Service name | Endpoint service | Why needed |
|---------------------|--------------|------------------|------------|
| **vpce-ssm** | SSM | com.amazonaws.ap-southeast-1.ssm | Core SSM API (SendCommand, GetCommandInvocation, etc.). Session Manager uses it to register and for control plane. |
| **vpce-ssmmessages** | SSM Messages | com.amazonaws.ap-southeast-1.ssmmessages | Data plane for Session Manager: streaming input/output between your session and the instance. |
| **vpce-ec2messages** | EC2 Messages | com.amazonaws.ap-southeast-1.ec2messages | Used by SSM Agent on the instance to poll for commands and report status. Required for Run Command and Session Manager. |

All three are required for Session Manager to work without internet egress.

---

## 3) Endpoint configuration

### 3.1 Subnets to use

- **Recommendation:** At least **2 AZs** for availability.
- **Chosen (from your VPC):**
  - **subnet-0f4a20184f9106c6c** (ap-southeast-1a) — same AZ as instance.
  - **subnet-05dfde4f4da3a8887** (ap-southeast-1b) — second AZ.

Use the same two subnets for all three endpoints. (You can add ap-southeast-1c later if you want three AZs.)

### 3.2 Security group for endpoints

Create **one** security group for all three endpoints.

**Name (explicit):** `atp-vpce-ssm-sg`

**Exact endpoint security group rules (both directions):**

| Direction | Type       | Protocol | Port | Destination / Source | Description                    |
|-----------|------------|----------|------|----------------------|--------------------------------|
| **Inbound**  | HTTPS      | TCP      | 443  | sg-07f5b0221b7e69efe | From EC2 instance SG only      |
| **Outbound** | All traffic| All      | All  | 0.0.0.0/0            | Default (or HTTPS 443 if locked) |

*Inbound:* Only the instance security group (sg-07f5b0221b7e69efe) can reach the endpoint ENIs on TCP 443.
*Outbound:* Interface endpoints do not initiate outbound to the internet for SSM; default "All traffic" to 0.0.0.0/0 is typical (or restrict to HTTPS 443 if policy requires).

**Why from instance SG:** Only the EC2 instance (and any other instances using the same SG) need to reach the endpoint ENIs. Restricting to the instance SG is tighter than VPC CIDR.

### 3.3 Private DNS

- **Enable “Private DNS”** for each of the three endpoints.
- **Effect:** In this VPC, the default DNS names (e.g. `ssm.ap-southeast-1.amazonaws.com`) resolve to the **private IPs of the endpoint ENIs** instead of the public AWS IPs. So SSM Agent and Session Manager traffic stays inside the VPC and never uses the internet.
- **Dependency:** VPC must have **enableDnsSupport** and **enableDnsHostnames** true (already verified above).

### 3.4 Policy (optional)

- Default “Full access” is fine. You can restrict to specific actions later (e.g. ssm:*, ssmmessages:*, ec2messages:*) via endpoint policy if your security policy requires it.

---

## 4) Step-by-step: Create endpoints (Console)

### 4.1 Create security group for endpoints

1. **VPC** → **Security groups** → **Create security group**.
2. **Name:** `atp-vpce-ssm-sg`.
3. **VPC:** vpc-09930b85e52722581.
4. **Inbound rules** → **Add rule:**
   - Type: **HTTPS**
   - Source: **Custom** → sg-07f5b0221b7e69efe
   - Description: “From EC2 instance SG”
5. **Outbound:** Leave default (All traffic 0.0.0.0/0) unless you have a policy to restrict it.
6. **Create security group.** Note the new SG ID (e.g. **sg-xxxxxxxx**).

### 4.2 Create endpoint: SSM

1. **VPC** → **Endpoints** → **Create endpoint**.
2. **Name (tag):** `vpce-ssm`.
3. **Service category:** AWS services.
4. **Services:** search **ssm** → select **com.amazonaws.ap-southeast-1.ssm**.
5. **VPC:** vpc-09930b85e52722581.
6. **Subnets:** select **ap-southeast-1a** (subnet-0f4a20184f9106c6c) and **ap-southeast-1b** (subnet-05dfde4f4da3a8887).
7. **Security group:** select the endpoint SG created above (`atp-vpce-ssm-sg`).
8. **Enable Private DNS name:** **Yes**.
9. **Create endpoint.**

### 4.3 Create endpoint: SSM Messages

1. **Create endpoint** again.
2. **Name:** `vpce-ssmmessages`.
3. **Service:** com.amazonaws.ap-southeast-1.ssmmessages.
4. **VPC:** same. **Subnets:** same two. **Security group:** same endpoint SG. **Private DNS:** Yes.
5. **Create endpoint.**

### 4.4 Create endpoint: EC2 Messages

1. **Create endpoint** again.
2. **Name:** `vpce-ec2messages`.
3. **Service:** com.amazonaws.ap-southeast-1.ec2messages.
4. **VPC:** same. **Subnets:** same two. **Security group:** same endpoint SG. **Private DNS:** Yes.
5. **Create endpoint.**

### 4.5 Optional: CLI equivalents

Replace `sg-ENDPOINT_SG_ID` with the ID of **atp-vpce-ssm-sg**.

```bash
# Create endpoint SG first (Console is easier; or use aws ec2 create-security-group + authorize-security-group-ingress).

# SSM
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-09930b85e52722581 \
  --vpc-endpoint-type Interface \
  --service-name com.amazonaws.ap-southeast-1.ssm \
  --subnet-ids subnet-0f4a20184f9106c6c subnet-05dfde4f4da3a8887 \
  --security-group-ids sg-ENDPOINT_SG_ID \
  --private-dns-enabled \
  --region ap-southeast-1

# SSM Messages
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-09930b85e52722581 \
  --vpc-endpoint-type Interface \
  --service-name com.amazonaws.ap-southeast-1.ssmmessages \
  --subnet-ids subnet-0f4a20184f9106c6c subnet-05dfde4f4da3a8887 \
  --security-group-ids sg-ENDPOINT_SG_ID \
  --private-dns-enabled \
  --region ap-southeast-1

# EC2 Messages
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-09930b85e52722581 \
  --vpc-endpoint-type Interface \
  --service-name com.amazonaws.ap-southeast-1.ec2messages \
  --subnet-ids subnet-0f4a20184f9106c6c subnet-05dfde4f4da3a8887 \
  --security-group-ids sg-ENDPOINT_SG_ID \
  --private-dns-enabled \
  --region ap-southeast-1
```

---

## 5) Validation plan

### 5.1 After endpoints are created (before tightening egress)

1. **Start a new Session Manager session** to i-087953603011543c5 (EC2 → Instances → Select instance → Connect → Session Manager).
2. In the session, run:  
   `echo "SSM via VPC endpoint OK" && curl -sS -m 2 http://169.254.169.254/latest/meta-data/instance-id`
3. **Expected:** You get a shell and the command prints the instance ID. Session is working via endpoints (Private DNS will direct SSM traffic to the endpoint ENIs).

### 5.2 Optional: tighten instance SG egress

After validation above, you can **remove** from the instance SG (sg-07f5b0221b7e69efe) any outbound rule that was only for SSM (e.g. if you had added 443 to specific SSM prefixes). With endpoints + Private DNS, SSM no longer needs internet 443 for `*.ssm.ap-southeast-1.amazonaws.com`, etc. Do not remove TCP 443 to 0.0.0.0/0 if the app still needs it for Crypto.com, Telegram, etc.

### 5.3 Test procedure (no SSH)

1. **EC2** → **Instances** → **i-087953603011543c5** → **Connect** → **Session Manager** → **Connect**.
2. In the session run:
   ```bash
   echo "SSM session OK"; curl -sS -m 2 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" >/dev/null && echo "IMDSv2 token OK" || true
   ```
3. **Pass:** Session opens and commands run. **Fail:** Session does not open or command times out → proceed to rollback.

**Optional — get VPC ID from instance (IMDSv2):** From an SSM session on the instance you can confirm the VPC ID:

```bash
TOKEN=$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
MAC=$(curl -sS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/mac)
VPC_ID=$(curl -sS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/network/interfaces/macs/${MAC}/vpc-id)
echo "VPC_ID=$VPC_ID"
```

Expected for this runbook: `VPC_ID=vpc-09930b85e52722581`.

### 5.4 Break-glass rollback

If SSM stops working after creating endpoints:

**Option A — Disable Private DNS (fast)**  
1. **VPC** → **Endpoints** → select each endpoint (vpce-ssm, vpce-ssmmessages, vpce-ec2messages).  
2. **Actions** → **Edit private DNS name** → **Disable** “Enable private DNS name” → **Save**.  
3. Retry Session Manager. Instance will resolve SSM hostnames to public IPs again and use internet (if egress still allows 443 to 0.0.0.0/0).

**Option B — Delete endpoints**  
1. **VPC** → **Endpoints** → select each endpoint → **Actions** → **Delete VPC endpoint** → confirm.  
2. After all three are deleted, SSM will use public AWS endpoints again (subject to egress rules).

**Post-rollback:** Confirm Session Manager connects and a simple command runs; then fix endpoint config (e.g. SG, subnets, Private DNS) and recreate if desired.

---

## 6) Cost + blast radius

### 6.1 Monthly cost estimate (order-of-magnitude)

Interface VPC endpoints are billed **per hour per Availability Zone** (each endpoint creates an ENI per subnet) plus **data processing** per GB. AWS does not waive endpoint charges for SSM; the cost appears under VPC/PrivateLink.

**Assumptions for this runbook:** 3 endpoints (vpce-ssm, vpce-ssmmessages, vpce-ec2messages), 2 AZs (ap-southeast-1a, ap-southeast-1b) → **6 endpoint ENI-hours per hour**. Typical SSM usage (Session Manager, Run Command) is low data volume (e.g. a few GB/month).

| Component | Estimate |
|-----------|----------|
| Hourly (per ENI, region-dependent) | ~$0.01/hour per ENI (order-of-magnitude; check [AWS PrivateLink pricing](https://aws.amazon.com/privatelink/pricing/) and [VPC pricing](https://aws.amazon.com/vpc/pricing/) for ap-southeast-1). |
| 6 ENIs × 730 hours/month | ~$44/month (hourly component) |
| Data processing | $0.01/GB for first 1 PB; SSM typically &lt;10 GB/month → &lt;$1/month |

**Order-of-magnitude total for the three interface endpoints:** **~$45–55/month** (hourly dominant). Confirm with AWS Pricing Calculator or the current region’s VPC/PrivateLink pricing page.

### 6.2 Blast radius if Private DNS is enabled and misconfigured

**Private DNS** for these endpoints changes resolution **VPC-wide** for the SSM/EC2 hostnames. If Private DNS is **enabled but misconfigured**, the blast radius is:

- **Who is affected:** Every resource in the VPC that resolves `ssm.ap-southeast-1.amazonaws.com`, `ssmmessages.ap-southeast-1.amazonaws.com`, or `ec2messages.ap-southeast-1.amazonaws.com` (SSM Agent on EC2 instances, Lambda in the VPC, ECS tasks using the VPC, etc.) will receive **private IPs** from the endpoint ENIs. If those ENIs are unreachable (wrong SG, wrong subnets, or endpoints deleted/failed), resolution still returns private IPs, so **all SSM/Session Manager and Run Command usage in the VPC fails** for as long as the misconfiguration persists.
- **Scope:** Entire VPC (all subnets, all AZs in that VPC). It is not limited to the instance or subnets where the endpoints were created.
- **Typical misconfigurations:** (1) Endpoint security group does not allow inbound 443 from the instance SG → instances cannot reach endpoint ENIs. (2) Endpoints in subnets without a route to the instances (e.g. wrong route table). (3) Private DNS enabled on only one or two of the three endpoints → mixed resolution (some hostnames to private IPs, others to public) → SSM can fail in non-obvious ways.
- **Mitigation:** Validate Session Manager immediately after enabling Private DNS (section 5). Keep the rollback steps (disable Private DNS or delete endpoints) ready; once Private DNS is disabled, resolution reverts to public AWS IPs and SSM works again if instance egress allows 443 to the internet.

---

## 7) Final hardening step (after validation)

**Apply this only after** endpoints vpce-ssm, vpce-ssmmessages, and vpce-ec2messages are **Available**, Private DNS is enabled, and a new Session Manager session to the instance has been confirmed working (section 5).

### 7.1 Outbound rule change: remove dependency on public internet for SSM

**Goal:** Keep HTTPS 443 for Crypto.com, Telegram, and other application APIs; ensure SSM traffic stays inside the VPC via the interface endpoints so that SSM no longer depends on public internet.

**Instance security group (sg-07f5b0221b7e69efe) — outbound rules to keep:**

| Type   | Protocol | Port | Destination   | Purpose |
|--------|----------|------|---------------|---------|
| HTTPS  | TCP      | 443  | 0.0.0.0/0     | Crypto.com, Telegram, market data, IP check, GitHub (optional), etc. |
| HTTP   | TCP      | 80   | 169.254.169.254/32 | Instance metadata only |
| Custom TCP | TCP  | 53   | 0.0.0.0/0 (or VPC DNS resolver) | DNS TCP |
| Custom UDP | UDP  | 53   | 0.0.0.0/0 (or VPC DNS resolver) | DNS UDP |

**What you can remove or avoid adding:** Any **outbound** rule that existed **only** to allow SSM over the public internet (e.g. 443 to SSM/EC2 prefix lists or to 0.0.0.0/0 purely for SSM). With Private DNS enabled, SSM hostnames resolve to the endpoint ENIs in the VPC; traffic never goes to the public SSM endpoints, so you do **not** need a special outbound rule for SSM to the internet.

**Explicit “do not break SSM” checklist:**

- [ ] **Private DNS:** All three endpoints (vpce-ssm, vpce-ssmmessages, vpce-ec2messages) have **Private DNS name** enabled. If any is disabled, that service’s hostname resolves to the public internet and the instance will need outbound 443 to reach it.
- [ ] **Endpoint SG (atp-vpce-ssm-sg):** Inbound TCP 443 from sg-07f5b0221b7e69efe is present. Without it, the instance cannot reach the endpoint ENIs.
- [ ] **Instance reachability:** Instance is in a subnet that can route to the endpoint subnets (same VPC; default route tables typically allow this). No NACL or firewall blocks 443 from instance to endpoint ENI IPs.
- [ ] **Do not remove TCP 443 to 0.0.0.0/0** from the instance SG if the app needs Crypto.com, Telegram, or other HTTPS services. Tightening should only remove SSM-specific rules (e.g. prefix lists for SSM); keeping one rule “HTTPS 443 to 0.0.0.0/0” is safe and required for the application.
- [ ] **After any change:** Open a **new** Session Manager session and run a simple command (e.g. `echo SSM OK`) before closing the runbook.

---

## 8) GO/NO-GO checklist

Before considering the change “closed”:

- [ ] **Endpoints created:** All three (vpce-ssm, vpce-ssmmessages, vpce-ec2messages) exist in vpc-09930b85e52722581, status **Available**.
- [ ] **Subnets:** Each endpoint has at least 2 subnets (ap-southeast-1a and ap-southeast-1b).
- [ ] **Security group:** atp-vpce-ssm-sg; inbound TCP 443 from sg-07f5b0221b7e69efe (instance SG).
- [ ] **Private DNS:** Enabled on all three endpoints.
- [ ] **Validation:** New Session Manager session opens to i-087953603011543c5 and a test command runs successfully.
- [ ] **Evidence:** Screenshots or logs saved (section 9).

**GO:** All items checked and evidence stored.  
**NO-GO:** Any item unchecked or SSM validation fails → fix or rollback.

---

## 9) Evidence to store (docs/audit)

Capture and keep in the repo (e.g. `docs/audit/VPC_ENDPOINTS_SSM_EVIDENCE.md` or similar):

1. **Endpoints list**  
   - Screenshot or CLI output: **VPC** → **Endpoints** filtered by this VPC, showing the three endpoints and state **Available**.
   - Optional CLI:  
     `aws ec2 describe-vpc-endpoints --filters "Name=vpc-id,Values=vpc-09930b85e52722581" "Name=service-name,Values=com.amazonaws.ap-southeast-1.ssm,com.amazonaws.ap-southeast-1.ssmmessages,com.amazonaws.ap-southeast-1.ec2messages" --region ap-southeast-1 --query 'VpcEndpoints[*].[ServiceName,VpcEndpointId,State]' --output table`

2. **Endpoint SG (atp-vpce-ssm-sg)**  
   - Screenshot of the endpoint security group: inbound HTTPS from sg-07f5b0221b7e69efe (see section 3.2 for full rules).

3. **SSM validation**  
   - Screenshot of Session Manager tab after **Connect** (session open).
   - Snippet of session output: e.g. `SSM session OK` and `IMDSv2 token OK` (or the echo + curl command from 5.3).

4. **Optional: DNS resolution**  
   - From an SSM session on the instance:  
     `nslookup ssm.ap-southeast-1.amazonaws.com`  
   - Expected: private IP(s) in 172.31.x.x (endpoint ENIs), not public AWS IPs.

---

## 10) Summary for approval

**Subnets chosen:**  
- **subnet-0f4a20184f9106c6c** (ap-southeast-1a)  
- **subnet-05dfde4f4da3a8887** (ap-southeast-1b)  

**Endpoint security group (atp-vpce-ssm-sg):**  
- New SG in vpc-09930b85e52722581.  
- Inbound: TCP 443 from **sg-07f5b0221b7e69efe** (instance SG).  
- Outbound: default (or HTTPS 443 only if locked). See section 3.2 for exact rules both directions.

**Endpoint names:** vpce-ssm, vpce-ssmmessages, vpce-ec2messages.

**Risks:**  
- Misconfigured SG (e.g. wrong source) → SSM cannot reach endpoints → Session Manager fails. Mitigation: validate immediately; rollback by disabling Private DNS or deleting endpoints.  
- Wrong subnet (e.g. no route to instance) → same. Mitigation: use the instance’s subnet plus one other in the same VPC.

Once you confirm there are no extra constraints (e.g. different subnet or SG policy), you can apply the runbook and then run validation and evidence capture as above.
