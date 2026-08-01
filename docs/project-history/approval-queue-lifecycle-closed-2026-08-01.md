# ApprovalQueue lifecycle — closed 2026-08-01

Read-only closeout. No alert threshold or production config changes.

## Verdict

| Piece | Status | PR |
|-------|--------|-----|
| `ApprovalQueueStale` (Telegram agent pending) | Live | #162 |
| `JarvisApprovalQueueStale` (ACW waiting) | Live | #234 |
| 7-day expire (agent pending + ACW `low`) | Live | #299 |
| Objective dedup (ACW waiting) | Live | #300 |
| Ops escalation (ACW `medium`/`high`, default ≥3d, once/task) | Live | #302 |
| Scheduler hourly maintenance | Live | `scheduler.check_approval_queue` |

**Priority closed.** Do not treat ApprovalQueue lifecycle as open work unless
stale metrics or alerts regress.

## Production verification (2026-08-01)

- Backend commit observed: `691677f7…` (`x-atp-backend-commit`).
- Public metrics (`/api/metrics`):

  | Metric | Value |
  |--------|-------|
  | `approval_queue_pending_total` | 0 |
  | `approval_queue_stale_total` | 0 |
  | `jarvis_approval_queue_waiting_total` | 0 |
  | `jarvis_approval_queue_stale_total` | 0 |

- Alert rules present in `scripts/aws/observability/alerts.yml` (+ promtool
  fixtures in `alerts.test.yml`).
- Unit coverage: `backend/tests/test_approval_queue_monitor.py` (stale stats,
  expire, dedup, escalate, maintenance aggregate).

## Defaults (env-overridable)

| Env | Default | Role |
|-----|---------|------|
| `APPROVAL_QUEUE_STALE_HOURS` | 24 | Stale metric / alert threshold |
| `APPROVAL_QUEUE_EXPIRE_DAYS` | 7 | Auto-expire age |
| `APPROVAL_QUEUE_JARVIS_EXPIRE_RISK_LEVELS` | `low` | ACW risks eligible to expire |
| `APPROVAL_QUEUE_JARVIS_ESCALATE_DAYS` | 3 | Ops Telegram escalate age |
| `APPROVAL_QUEUE_JARVIS_ESCALATE_RISK_LEVELS` | `medium,high` | ACW risks eligible to escalate |
| `APPROVAL_QUEUE_JARVIS_DEDUP_ENABLED` | `true` | Objective fingerprint dedup |
| `APPROVAL_QUEUE_JARVIS_ESCALATE_ENABLED` | `true` | Ops escalate toggle |

## What remains (not this closeout)

- Human review of any future medium/high waiters that escalate to ops.
- Capacity split of observability/canary only if host memory/swap pressure
  returns (`swap_investigation.md` §7.4).
