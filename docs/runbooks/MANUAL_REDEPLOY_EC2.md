# Manual redeploy on EC2 (when SSM is Undeliverable)

When `./redeploy.sh` reports **Status: Undeliverable**, the SSM command never reached the instance. Deploy directly on the box via SSH or a new SSM session.

## One-time full redeploy (backend + frontend)

On the EC2 instance (SSH or SSM start-session):

```bash
cd /home/ubuntu/automated-trading-platform
git pull origin main
docker compose --profile aws build --no-cache backend-aws frontend-aws
docker compose --profile aws up -d
sudo systemctl restart nginx
docker compose --profile aws ps
```

First run can take 5–10 minutes (no-cache build). Then verify:

```bash
curl -s http://localhost:8002/ping_fast
```

From your machine: `curl -s https://dashboard.hilovivo.com/api/ping_fast`

## Backend-only quick redeploy

If only backend changed:

```bash
cd /home/ubuntu/automated-trading-platform
git pull origin main
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws up -d backend-aws
```
