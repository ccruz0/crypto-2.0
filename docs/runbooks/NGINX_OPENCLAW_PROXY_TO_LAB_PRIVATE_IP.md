# NGINX: proxy /openclaw/ to LAB private IP

## Goal
Make PROD proxy `/openclaw/` to LAB OpenClaw over the VPC private IP.

## Facts
- PROD (atp-rebuild-2026): private IP 172.31.32.169
- LAB (atp-lab-ssm-clean): private IP 172.31.3.214
- LAB OpenClaw: http://172.31.3.214:8080/ returns HTTP 200
- PROD nginx site file: /etc/nginx/sites-enabled/default
- Current issue: proxy_pass points to old public IP 52.77.216.100

## Minimal diff
Replace:
- `proxy_pass http://52.77.216.100:8080/;`
with:
- `proxy_pass http://172.31.3.214:8080/;`

## Recommended fix (idempotent script)
On PROD:
```bash
cd /home/ubuntu/automated-trading-platform
git pull origin main
sudo bash scripts/openclaw/fix_openclaw_proxy_prod.sh
```

## Expected verification
- From PROD:
  - `curl -I http://172.31.3.214:8080/` → HTTP 200
- From anywhere:
  - `curl -I https://dashboard.hilovivo.com/openclaw/` → HTTP 401 (Basic Auth)

## If it fails
- Inspect nginx errors:

```bash
sudo tail -n 120 /var/log/nginx/error.log
```

- Check LAB reachability from PROD:

```bash
curl -sS -m 5 -I http://172.31.3.214:8080/ | head -n 20
```

- Roll back using the backup printed by the script.
