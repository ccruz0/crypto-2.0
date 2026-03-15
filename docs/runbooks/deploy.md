# Deploy Runbook

Canonical procedure for deploying the Automated Trading Platform to production (AWS).

---

## Policy

- **GitHub is the single source of truth** for code.
- Production runs on **one EC2 instance** (atp-rebuild-2026). All production operations are executed via **SSH** (or SSM when SSH is unavailable) on that instance.
- Deployment is **deploy-by-commit**: what is on `main` (or the chosen branch) is what gets deployed.

---

## Standard deployment (recommended)

1. **From your machine**: Push to `main` (or trigger the deploy workflow manually).
2. **GitHub Actions**: The workflow **"Deploy to AWS EC2 (Session Manager)"** runs and deploys to PROD (i-087953603011543c5).
3. **Verify**: After the run completes:
   - Check workflow success in GitHub Actions.
   - Open https://dashboard.hilovivo.com and confirm the app loads.
   - Run: `./scripts/aws/verify_prod_public.sh` (or `prod_status.sh`) to hit `/api/health`.

Detailed checklist: [POST_DEPLOY_VERIFICATION.md](../aws/POST_DEPLOY_VERIFICATION.md).

---

## Manual deploy (SSH on EC2)

When you need to deploy manually (e.g. SSM unavailable, or one-off fix):

1. **Connect**:
   ```bash
   ssh ubuntu@dashboard.hilovivo.com
   # or ssh ubuntu@<PROD_IP>
   cd /home/ubuntu/automated-trading-platform
   ```

2. **Pull and run** (use the project’s standard deploy script if available):
   ```bash
   git pull origin main
   docker compose --profile aws pull
   docker compose --profile aws up -d --remove-orphans
   ```

   **If `backend/requirements.txt` changed** (or you see `ModuleNotFoundError` like `pydantic_settings`), rebuild the image:
   ```bash
   docker compose --profile aws build --no-cache backend-aws
   docker compose --profile aws up -d backend-aws
   ```
   See [backend/DOCKER_BUILD_CONTEXT.md](../../backend/DOCKER_BUILD_CONTEXT.md) for verification commands.

3. **Verify**:
   ```bash
   docker compose --profile aws ps
   curl -s http://localhost:8002/api/health
   ```

4. Optionally run the full [POST_DEPLOY_VERIFICATION.md](../aws/POST_DEPLOY_VERIFICATION.md) checklist.

---

## Command reference (on EC2)

From [contracts/deployment_aws.md](../contracts/deployment_aws.md):

| Action | Command |
|--------|---------|
| Status | `docker compose --profile aws ps` |
| Logs | `docker compose --profile aws logs -n 200 backend-aws` |
| Deploy/update | `docker compose --profile aws pull && docker compose --profile aws up -d --remove-orphans` |

---

## Rollback

If the project has a rollback script (e.g. `scripts/rollback_aws.sh`), use it with the desired commit SHA. Otherwise, on EC2:

```bash
cd /home/ubuntu/automated-trading-platform
git checkout <commit-sha>
docker compose --profile aws up -d --build
```

Then verify health and dashboard.

---

## Related

- [Restart services](restart-services.md)
- [AWS setup](../infrastructure/aws-setup.md)
- [Deployment contract](../contracts/deployment_aws.md)
- [RUNBOOK_INDEX.md](../aws/RUNBOOK_INDEX.md) — When to use each runbook
