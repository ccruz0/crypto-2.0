# Instance source of truth (PROD / LAB)

**Use this table as the single reference for instance names, IPs, and roles.**  
When in doubt, prefer dashboard.hilovivo.com or the EC2 console for current public IP.

---

## Instances

| Role | Instance name | Instance ID | Private IP | Public IP | Purpose |
|------|---------------|-------------|------------|------------|---------|
| **PROD** | atp-rebuild-2026 | i-087953603011543c5 | 172.31.32.169 | 52.220.32.147 | Serves https://dashboard.hilovivo.com. Nginx, frontend :3000, backend :8002, db, market-updater. Proxies /openclaw/ to LAB. |
| **LAB** | atp-lab-ssm-clean | i-0d82c172235770a0d | 172.31.3.214 | (varies / none) | OpenClaw only. http://172.31.3.214:8080 |

**Region:** ap-southeast-1

---

## Access

| What | How |
|------|-----|
| Dashboard | https://dashboard.hilovivo.com |
| OpenClaw UI | https://dashboard.hilovivo.com/openclaw/ (Basic Auth) |
| SSH to PROD | `ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147` (or use EC2 Instance Connect; confirm public IP in console) |
| LAB (SSM) | `aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1` |

---

## Verification (quick)

**From PROD:**

```bash
curl -sS -m 5 -I http://172.31.3.214:8080/ | head -5   # LAB OpenClaw → 200
curl -sS -m 8 -I https://dashboard.hilovivo.com/openclaw/ | head -10   # public → 401
```

**Expected:** LAB 200, public 401 (Basic Auth).

---

## Other instances (do not use for PROD/LAB)

| Name | Instance ID | Note |
|------|-------------|------|
| atp-lab-openclaw | i-090a1b69a56d2adbe | Keep **stopped**. Current LAB = atp-lab-ssm-clean. |
| crypto 2.0 | i-08726dc37133b2454 | Ignored. Do not use for production. |
