# Restart Services Runbook

How to restart production services on AWS (Docker Compose, profile `aws`).

---

## Where to run

All commands are run **on the EC2 instance** (atp-rebuild-2026), in the project directory:

```bash
ssh ubuntu@dashboard.hilovivo.com
cd /home/ubuntu/crypto-2.0
```

If SSH is unavailable, use **AWS Systems Manager Session Manager** and then run the same commands. See [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](../aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md) if SSM shows ConnectionLost.

---

## Restart one service

```bash
# Backend only
docker compose --profile aws restart backend-aws

# Frontend only
docker compose --profile aws restart frontend-aws

# Market updater only
docker compose --profile aws restart market-updater-aws
```

---

## Restart all services (profile aws)

```bash
docker compose --profile aws restart
```

---

## After restart

1. **Status**:
   ```bash
   docker compose --profile aws ps
   ```

2. **Health**:
   ```bash
   curl -s http://localhost:8002/api/health
   curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/
   ```

3. **Logs** (if something failed):
   ```bash
   docker compose --profile aws logs -n 100 backend-aws
   docker compose --profile aws logs -n 100 frontend-aws
   ```

---

## Nginx (host, not in compose)

If you need to restart Nginx on the host (e.g. after config change):

```bash
sudo systemctl restart nginx
# or
sudo nginx -s reload
```

Use the project’s or ops runbook for Nginx config path and reload procedure.

---

## Related

- [Deploy runbook](deploy.md)
- [Deployment contract](../contracts/deployment_aws.md)
- [AWS setup](../infrastructure/aws-setup.md)
- [Dashboard health check](dashboard_healthcheck.md) — Full troubleshooting if the dashboard is down
