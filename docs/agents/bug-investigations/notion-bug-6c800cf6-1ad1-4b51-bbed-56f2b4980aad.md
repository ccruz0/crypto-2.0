# Bug investigation: E2E flow test: add runbook link to README

- **Notion page id**: `6c800cf6-1ad1-4b51-bbed-56f2b4980aad`
- **Priority**: `High`
- **Project**: `Crypto Trading`
- **Type**: `Bug`
- **GitHub link**: ``

## Inferred area

- **Area**: Monitoring / Infrastructure
- **Matched rules**: monitoring-infra

## Affected modules

- `backend/app/api/routes_monitoring.py`
- `backend/app/api/routes_debug.py`
- `backend/app/main.py`
- `docker-compose.yml`

## Relevant docs

- [docs/architecture/system-map.md](../../architecture/system-map.md)
- [docs/agents/context.md](../context.md)
- [docs/agents/task-system.md](../task-system.md)
- [docs/decision-log/README.md](../../decision-log/README.md)
- [docs/operations/monitoring.md](../../operations/monitoring.md)
- [docs/aws/RUNBOOK_INDEX.md](../../aws/RUNBOOK_INDEX.md)

## Relevant runbooks

- [docs/runbooks/deploy.md](../../runbooks/deploy.md)
- [docs/runbooks/restart-services.md](../../runbooks/restart-services.md)
- [docs/runbooks/dashboard_healthcheck.md](../../runbooks/dashboard_healthcheck.md)
- [docs/runbooks/502_BAD_GATEWAY.md](../../runbooks/502_BAD_GATEWAY.md)
- [docs/runbooks/DASHBOARD_UNREACHABLE_RUNBOOK.md](../../runbooks/DASHBOARD_UNREACHABLE_RUNBOOK.md)

## Bug details

- **Reported symptom**: Add a single line to the repo README linking to docs/runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md. No code logic changes. Purpose: exercise the full Notion → Cursor → deploy flow for review.
- **Reproducible**: (to be confirmed)
- **Severity**: (inferred from priority: High)

## Investigation checklist

- [ ] Confirm current behavior (logs, health endpoint, dashboard)
- [ ] Identify root cause in affected module(s)
- [ ] Determine smallest safe fix
- [ ] Verify fix does not affect unrelated areas
- [ ] Update relevant docs/runbooks if behavior changes
- [ ] Validate (tests/lint/manual) before marking deployed

---

- Investigation note touched by agent callback (no overwrite).
