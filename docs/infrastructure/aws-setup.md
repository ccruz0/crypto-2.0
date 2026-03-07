# AWS Setup

Production runs on a single EC2 instance. This doc summarizes instance IDs, access, and where to find detailed runbooks.

---

## Instances (Reference)

| Role | Name | Instance ID | Notes |
|------|------|-------------|--------|
| **PROD** | atp-rebuild-2026 | i-087953603011543c5 | Dashboard, backend, trading, alerts. Deploy target. |
| **LAB** | atp-lab-ssm-clean | i-0d82c172235770a0d | OpenClaw / testing; no production secrets. |

**PROD** public IP can change on stop/start. Prefer **dashboard.hilovivo.com** or check EC2 Console for current IPv4. Use that IP for SSH and for Crypto.com API whitelist.

---

## Access

- **SSH**: `ssh ubuntu@<EC2_IP>` or alias to `dashboard.hilovivo.com` (key from GitHub secrets / local config).
- **SSM**: Session Manager for when SSH is unavailable. See [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](../aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md) if PROD shows ConnectionLost.

---

## GitHub (Deploy / Actions)

| Variable / Secret | Use |
|-------------------|-----|
| **EC2_HOST** | Deploy target host (e.g. `dashboard.hilovivo.com` or PROD IP). |
| **EC2_KEY** | SSH private key for `ubuntu@EC2_HOST`. |
| **API_BASE_URL** | Backend base URL (e.g. `https://dashboard.hilovivo.com/api`). |
| **AWS_ACCESS_KEY_ID** / **AWS_SECRET_ACCESS_KEY** | For workflows using SSM (deploy, Guard/Sentinel, etc.). |

---

## Project Path on EC2

```bash
cd /home/ubuntu/automated-trading-platform
```

All production commands (docker compose, scripts) assume this path.

---

## Docker Compose (Production)

- Profile: **`--profile aws`**
- Commands: see [deployment_aws.md](../contracts/deployment_aws.md) and [restart-services.md](../runbooks/restart-services.md).

---

## Scripts (from repo, run locally or on instance)

| Script | Purpose |
|--------|---------|
| `./scripts/aws/verify_prod_public.sh [URL]` | Curl `/api/health`; exit 0 if 200. |
| `./scripts/aws/prod_status.sh [URL]` | API + optional SSM status. |
| `./scripts/aws/aws_audit_live.sh` | Instances, IAM, SGs, SSM (requires AWS CLI). |

---

## Runbooks (quick index)

- [AWS_PROD_QUICK_REFERENCE.md](../aws/AWS_PROD_QUICK_REFERENCE.md) — Instance IDs, secrets, workflows, runbook list.
- [RUNBOOK_INDEX.md](../aws/RUNBOOK_INDEX.md) — When to use each runbook.
- [POST_DEPLOY_VERIFICATION.md](../aws/POST_DEPLOY_VERIFICATION.md) — After deploy or EC2_HOST change.
- [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](../aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md) — PROD SSM ConnectionLost: reboot and diagnose.
- [Deploy runbook](../runbooks/deploy.md) — Canonical deploy procedure.
- [Restart services](../runbooks/restart-services.md) — Restart and verify services.

---

## Related

- [Docker setup](docker-setup.md)
- [Crypto.com connection (AWS)](../AWS_CRYPTO_COM_CONNECTION.md)
