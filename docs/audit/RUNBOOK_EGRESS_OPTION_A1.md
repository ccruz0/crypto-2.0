# Runbook: Apply Option A (A1) Egress Rules — EC2 52.77.216.100

**Goal:** Restrict outbound traffic to required ports only; validate; provide rollback in &lt;60s.  
**Access:** SSM Session Manager only (no SSH). No secrets in this document.

---

## Pre-requisites

- You have SSM access to the instance (AWS Console → EC2 → Instance → Connect → Session Manager).
- From the SSM shell you have: `aws` CLI (pre-installed on Amazon Linux 2; on Ubuntu may need `sudo snap install aws-cli --classic` or use instance IAM role from your laptop if preferred).
- **Optional but recommended:** Run the “Current-state capture” and “Validation (baseline)” from your laptop or a jump host with AWS CLI and same IAM permissions, so you have a copy of the SG rules and a baseline before changing anything.

---

## 1) Identify the security group

**From an SSM session on the instance** (or any machine with `aws` and credentials for the instance’s region/account):

```bash
# 1.1 Get instance ID via IMDSv2 (run this ON the instance via SSM)
TOKEN=$(curl -sS -m 2 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
INSTANCE_ID=$(curl -sS -m 2 "http://169.254.169.254/latest/meta-data/instance-id" -H "X-aws-ec2-metadata-token: $TOKEN")
echo "InstanceId: $INSTANCE_ID"

# 1.2 Get security group ID(s) and name(s) for this instance
aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].SecurityGroups[*].[GroupId,GroupName]' \
  --output table
```

**Record:**

- **Primary SG (used for egress):** `sg-xxxxxxxx` and its **Name** (e.g. `launch-wizard-1` or `atp-prod-sg`).  
- If multiple SGs are attached, the one that currently has “All traffic” → 0.0.0.0/0 is the one to edit (often there is only one).

**Set for later steps (replace with your value):**

```bash
SG_ID=sg-xxxxxxxx
```

---

## 2) Current-state capture

**2.1 List current outbound rules (from SSM shell or laptop):**

```bash
aws ec2 describe-security-groups --group-ids "$SG_ID" \
  --query 'SecurityGroups[0].IpPermissionsEgress' \
  --output json
```

**2.2 Save to file (so you can rollback):**

```bash
aws ec2 describe-security-groups --group-ids "$SG_ID" \
  --query 'SecurityGroups[0].IpPermissionsEgress' \
  --output json > /tmp/sg_egress_backup_$(date +%Y%m%d_%H%M%S).json
```

**2.3 What to record (screenshot or notes):**

- For each egress rule note:
  - **IpProtocol** (e.g. `-1`, `tcp`, `udp`)
  - **FromPort** / **ToPort** (if present)
  - **IpRanges[].CidrIp** (e.g. `0.0.0.0/0`)
- You should see at least one rule: **IpProtocol: -1**, **CidrIp: 0.0.0.0/0** (allow all). That is the rule we will revoke.

**2.4 (Optional) Human-readable table:**

```bash
aws ec2 describe-security-groups --group-ids "$SG_ID" \
  --query 'SecurityGroups[0].IpPermissionsEgress[*].[IpProtocol,FromPort,ToPort,IpRanges[0].CidrIp]' \
  --output table
```

---

## 3) Change plan (Option A — A1)

- **Remove:** One egress rule: **All traffic (protocol -1)** to **0.0.0.0/0**.
- **Add:** Four egress rules:
  - TCP 443 → 0.0.0.0/0
  - TCP 80 → 169.254.169.254/32
  - UDP 53 → 0.0.0.0/0 (or VPC resolver; see note below)
  - TCP 53 → 0.0.0.0/0 (or same as UDP)

**VPC DNS:** If you want to restrict DNS to the VPC resolver only, use **169.254.169.253/32** for UDP 53 and TCP 53 instead of 0.0.0.0/0. The commands below use 0.0.0.0/0 for DNS so they work even if the resolver is not at 169.254.169.253.

### 3.1 Ubuntu instances: apt after A1 (use HTTPS, not HTTP)

With A1, outbound **TCP 80** is only to `169.254.169.254` (metadata). Ubuntu’s default apt sources use **HTTP** (port 80), so `apt update` / `apt install` will fail with “Network is unreachable” unless you either allow TCP 80 to 0.0.0.0/0 temporarily or switch apt to **HTTPS** (port 443, already allowed).

**Option A — Switch apt to HTTPS (recommended, no new egress rule):** Run these **on the instance** via SSM (use `|` as the delimiter in `sed`, not `/`):

```bash
sudo sed -i.bak 's|http://ap-southeast-1.ec2.archive.ubuntu.com|https://ap-southeast-1.ec2.archive.ubuntu.com|g' /etc/apt/sources.list
sudo sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list
sudo sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list
sudo apt update || true
sudo apt install -y apt-transport-https ca-certificates
sudo apt update
```

Or from the repo: `bash scripts/aws/apt-sources-https.sh`.

**Option B — Temporary egress:** Add outbound TCP 80 → 0.0.0.0/0, run `apt update` / `apt upgrade`, then remove the rule (see EGRESS_HARDENING_DESIGN.md).

---

## 4) AWS Console checklist (security group egress edit)

Use this if you prefer clicking in the console.

1. **AWS Console** → **EC2** → **Instances**.
2. Select instance with **Public IP 52.77.216.100** (or find by Instance ID from step 1).
3. **Security** tab → under **Security groups**, click the **Security group ID** (e.g. `sg-xxxxxxxx`).
4. **Outbound rules** tab → **Edit outbound rules**.
5. **Record** existing rules (screenshot or copy table) for rollback.
6. **Remove** the rule:
   - Type: **All traffic**
   - Destination: **0.0.0.0/0**
7. **Add** the following rules (keep any other existing rules you need):

   | Type        | Protocol | Port range | Destination        | Description          |
   |------------|----------|------------|---------------------|----------------------|
   | HTTPS      | TCP      | 443        | 0.0.0.0/0           | Application APIs     |
   | HTTP       | TCP      | 80         | 169.254.169.254/32  | Instance metadata    |
   | Custom UDP | UDP      | 53         | 0.0.0.0/0           | DNS                  |
   | Custom TCP | TCP      | 53         | 0.0.0.0/0           | DNS (TCP)            |

8. **Save** outbound rules.
9. Proceed to **Section 6** (Validation) from an SSM session on the instance.

---

## 5) CLI commands (apply change from SSM shell)

Run these **from the SSM session on the instance** (or from a machine with `aws` and same region/account). Replace `sg-xxxxxxxx` with your `SG_ID`.

```bash
SG_ID=sg-xxxxxxxx   # <-- SET THIS

# 5.1 Revoke "All traffic" egress (protocol -1, 0.0.0.0/0)
aws ec2 revoke-security-group-egress --group-id "$SG_ID" \
  --ip-permissions '[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]'

# 5.2 Add TCP 443 -> 0.0.0.0/0
aws ec2 authorize-security-group-egress --group-id "$SG_ID" \
  --ip-permissions '[{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "HTTPS APIs"}]}]'

# 5.3 Add TCP 80 -> 169.254.169.254/32 (metadata)
aws ec2 authorize-security-group-egress --group-id "$SG_ID" \
  --ip-permissions '[{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "169.254.169.254/32", "Description": "Instance metadata"}]}]'

# 5.4 Add UDP 53 -> 0.0.0.0/0 (DNS)
aws ec2 authorize-security-group-egress --group-id "$SG_ID" \
  --ip-permissions '[{"IpProtocol": "udp", "FromPort": 53, "ToPort": 53, "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "DNS"}]}]'

# 5.5 Add TCP 53 -> 0.0.0.0/0 (DNS TCP)
aws ec2 authorize-security-group-egress --group-id "$SG_ID" \
  --ip-permissions '[{"IpProtocol": "tcp", "FromPort": 53, "ToPort": 53, "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "DNS TCP"}]}]'
```

**If revoke fails** (e.g. "rule not found"): note the exact error. Some accounts require the full rule structure (e.g. with `"Ipv6Ranges": []`, `"PrefixListIds": []`, `"UserIdGroupPairs": []`). In that case, from your backup JSON (step 2.2) copy the single egress rule that has `"IpProtocol": "-1"` and `"CidrIp": "0.0.0.0/0"` (including any empty arrays) and pass it to `--ip-permissions`.

---

## 6) Validation script (run from SSM shell on the instance)

Run the whole block. It uses only `curl`, `openssl`, and shell (no websocat). **Do not paste any secrets.**

```bash
PASS=0
FAIL=0
report() { echo "[$1] $2"; [ "$1" = "PASS" ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1)); }

# --- DNS ---
echo "=== DNS ==="
if command -v getent >/dev/null 2>&1; then
  getent hosts api.crypto.com >/dev/null 2>&1 && report PASS "DNS resolve api.crypto.com" || report FAIL "DNS resolve api.crypto.com"
else
  (nslookup api.crypto.com >/dev/null 2>&1 || host api.crypto.com >/dev/null 2>&1) && report PASS "DNS resolve api.crypto.com" || report FAIL "DNS resolve api.crypto.com"
fi

# --- HTTPS (curl) ---
echo "=== HTTPS ==="
for host in api.crypto.com stream.crypto.com api.telegram.org api.coingecko.com; do
  if curl -sS --max-time 10 -o /dev/null -w "%{http_code}" "https://$host/" 2>/dev/null | grep -qE '^[0-9]+$'; then
    report PASS "HTTPS $host"
  else
    # Fallback: TCP connect via openssl (no HTTP)
    if openssl s_client -connect "$host:443" -servername "$host" </dev/null 2>/dev/null | grep -q "Server certificate"; then
      report PASS "TLS $host:443"
    else
      report FAIL "HTTPS/TLS $host"
    fi
  fi
done

# --- IMDSv2 metadata (token + instance-id) ---
echo "=== IMDSv2 metadata check (instance-id) ==="
TOKEN="$(curl -sS -m 2 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || true)"
if [ -z "$TOKEN" ]; then
  report FAIL "IMDSv2 token request (no token)"
else
  report PASS "IMDSv2 token request"
  IID="$(curl -sS -m 2 "http://169.254.169.254/latest/meta-data/instance-id" -H "X-aws-ec2-metadata-token: $TOKEN" 2>/dev/null || true)"
  if echo "$IID" | grep -q '^i-'; then
    report PASS "IMDSv2 instance-id ok: $IID"
  else
    report FAIL "IMDSv2 instance-id empty/unexpected: '$IID'"
  fi
fi

# --- Summary ---
echo "=== Summary ==="
echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" -eq 0 ] && echo "Go/No-Go: GO" || echo "Go/No-Go: NO-GO"
```

**Interpretation:**

- **Go:** All checks PASS; FAIL = 0 → **GO**.
- **No-Go:** Any FAIL → **NO-GO**; proceed to rollback (Section 7).

**Note:** `stream.crypto.com` is checked with HTTPS/TLS on 443 (WSS uses the same port). No websocat needed. The metadata check uses **IMDSv2** (PUT token, then GET instance-id with token) so it works on instances that require IMDSv2.

---

## 7) Rollback (restore previous egress in &lt;60 seconds)

**7.1 Restore via CLI (remove new rules, re-add “All traffic”):**

Run from SSM or any machine with `aws` and the same `SG_ID`. Ignores “rule not found” so safe if some rules were already removed.

```bash
SG_ID=sg-xxxxxxxx   # <-- SET THIS

# Revoke the four rules we added (ignore errors if already gone)
aws ec2 revoke-security-group-egress --group-id "$SG_ID" \
  --ip-permissions '[{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]' 2>/dev/null || true
aws ec2 revoke-security-group-egress --group-id "$SG_ID" \
  --ip-permissions '[{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "169.254.169.254/32"}]}]' 2>/dev/null || true
aws ec2 revoke-security-group-egress --group-id "$SG_ID" \
  --ip-permissions '[{"IpProtocol": "udp", "FromPort": 53, "ToPort": 53, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]' 2>/dev/null || true
aws ec2 revoke-security-group-egress --group-id "$SG_ID" \
  --ip-permissions '[{"IpProtocol": "tcp", "FromPort": 53, "ToPort": 53, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]' 2>/dev/null || true

# Re-add default "All traffic"
aws ec2 authorize-security-group-egress --group-id "$SG_ID" \
  --ip-permissions '[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]'

echo "Rollback done: default egress restored."
```

**7.2 Rollback via AWS Console (fastest):**

1. **EC2** → **Security Groups** → select **sg-xxxxxxxx**.
2. **Outbound rules** → **Edit outbound rules**.
3. **Remove** the four rules you added (HTTPS 443, HTTP 80 to metadata, UDP 53, TCP 53).
4. **Add** rule: Type **All traffic**, Destination **0.0.0.0/0**.
5. **Save** rules.

**7.3 Post-rollback validation (from SSM):**

- Confirm SSM session still works (you’re in the shell).
- Run the same validation block as in Section 6 (DNS, HTTPS to api.crypto.com, api.telegram.org, api.coingecko.com, metadata). All should **PASS** after rollback.

---

## 8) Go / No-Go gate

| Condition                         | Result  |
|----------------------------------|---------|
| All validation checks PASS       | **GO**  |
| Any validation check FAIL        | **NO-GO** → rollback (Section 7), then re-check validation |
| SSM disconnected after change    | **NO-GO** → rollback from another machine with AWS CLI/Console using the same SG ID |

**After GO:** Option A (A1) egress is in place. Application egress remains constrained by `egress_guard` allowlist in code; no application code was modified in this runbook.

---

## Quick reference

- **Instance (example):** 52.77.216.100  
- **SG (set yourself):** `SG_ID=sg-xxxxxxxx`  
- **Backup egress:** `aws ec2 describe-security-groups --group-ids $SG_ID --query 'SecurityGroups[0].IpPermissionsEgress' --output json > /tmp/sg_egress_backup_$(date +%Y%m%d_%H%M%S).json`  
- **Rollback (console):** Edit outbound → remove 4 rules → add All traffic 0.0.0.0/0 → Save.
