# IMDSv2 required — clear the EC2 warning

EC2 shows: **"EC2 recommends setting IMDSv2 to required"** on the instance details. Enabling it improves security (metadata only via session tokens). This runbook clears the warning and ensures our code works with IMDSv2.

---

## 1. What we fixed (code)

These use **IMDSv2** (PUT token, then GET with `X-aws-ec2-metadata-token`) so they keep working after you set IMDSv2 to required:

- `scripts/verify_ec2_ip_and_health.sh` — EC2 public IP
- `backend/scripts/get_aws_ip.py` — public IP for Crypto.com whitelist
- `backend/app/utils/http_client.py` — `is_aws_metadata_reachable()`

So you can safely enable IMDSv2 required on PROD and LAB.

---

## 2. Enable IMDSv2 required (optional)

**Console:** EC2 → Instances → select instance → **Actions** → **Instance settings** → **Modify instance metadata options** → set **IMDSv2** to **Required** → Save.

**CLI (from your Mac, with AWS credentials):**

```bash
# PROD
aws ec2 modify-instance-metadata-options \
  --instance-id i-087953603011543c5 \
  --http-tokens required \
  --http-put-response-hop-limit 1 \
  --region ap-southeast-1

# LAB (OpenClaw)
aws ec2 modify-instance-metadata-options \
  --instance-id i-0d82c172235770a0d \
  --http-tokens required \
  --http-put-response-hop-limit 1 \
  --region ap-southeast-1
```

After this, the yellow warning in the console goes away. No reboot needed.

---

## 3. If something breaks after enabling

If any script or app still uses IMDSv1 (plain GET to `169.254.169.254/latest/meta-data/...` without a token), it will get **403 Forbidden**. Fix by using the IMDSv2 flow:

1. `PUT http://169.254.169.254/latest/api/token` with header `X-aws-ec2-metadata-token-ttl-seconds: 21600`
2. `GET http://169.254.169.254/latest/meta-data/<path>` with header `X-aws-ec2-metadata-token: <token>`

To roll back (allow IMDSv1 again):

```bash
aws ec2 modify-instance-metadata-options \
  --instance-id i-087953603011543c5 \
  --http-tokens optional \
  --region ap-southeast-1
```

---

## 4. Security group

Instance metadata is on link-local `169.254.169.254`. Outbound rules don’t need to allow it explicitly; ensure nothing blocks the instance from reaching that IP (no egress block to 169.254.169.254).
