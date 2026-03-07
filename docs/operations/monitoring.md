# Monitoring and Operations

How to monitor the Automated Trading Platform and respond to common issues.

---

## Health checks

- **Backend**: `GET /api/health` (e.g. `https://dashboard.hilovivo.com/api/health`).
- **Frontend**: Load `https://dashboard.hilovivo.com` and confirm the UI loads.
- **From repo**: Run `./scripts/aws/verify_prod_public.sh` or `./scripts/aws/prod_status.sh` to verify PROD API (and optionally SSM).

---

## Dashboard diagnostic script

**From your machine** (with SSH or SSM access configured):

```bash
cd /path/to/automated-trading-platform
bash scripts/debug_dashboard_remote.sh
```

This script checks:

- Container status and health (backend, frontend, db, market-updater)
- Backend API connectivity (host and Docker network)
- Database connectivity from backend
- External request path (domain → nginx → services)
- Recent error logs from services and Nginx

Use it when the dashboard is 502, blank, or unhealthy.

---

## Runbooks (when something is wrong)

| Situation | Runbook |
|-----------|---------|
| Dashboard 502 / blank / not loading | [dashboard_healthcheck.md](../runbooks/dashboard_healthcheck.md) |
| After a deploy or config change | [POST_DEPLOY_VERIFICATION.md](../aws/POST_DEPLOY_VERIFICATION.md) |
| PROD SSM ConnectionLost | [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](../aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md) |
| Full list of runbooks | [RUNBOOK_INDEX.md](../aws/RUNBOOK_INDEX.md) |

---

## Monitoring UI (in-app)

- **Monitoring tab**: Data from `/api/monitoring/summary` (alerts, throttle, status).
- **Telegram messages / audit**: `/api/monitoring/telegram-messages` for throttle and audit data.

Backend logs (and optional centralized logging) are the source for deeper debugging.

---

## Alerts and throttle

- Alerts and trades are throttled by **SignalThrottle** (price change and cooldown).
- Blocked events are logged (e.g. `SKIP_COOLDOWN_ACTIVE`) and visible in monitoring/audit data.
- See [Trading strategy](../trading-strategy/strategy.md) for throttle behavior.

---

## Related

- [Dashboard Diagnostic System](../monitoring/DASHBOARD_DIAGNOSTIC_SYSTEM.md)
- [System overview](../architecture/system-overview.md)
- [Infrastructure (AWS)](../infrastructure/aws-setup.md)
- [Restart services](../runbooks/restart-services.md)
