# Telegram agent quiet mode

Reduce Telegram noise so the user only receives **actionable** messages.

## Objective

User receives only:

1. **Final deploy approval** — when a task reaches ready-for-deploy
2. **Critical failure** — when a task requires attention (stuck after max retries, system cannot recover, deployment failed)

Everything else is silent or summarized (logs unchanged).

## Enable quiet mode

Set in environment:

```bash
AGENT_TELEGRAM_ONLY_DEPLOY_AND_CRITICAL=1
```

(or `true` / `yes`). When set, only **DEPLOY** and **CRITICAL** messages are sent to Telegram.

## Message categories

| Level      | Sent to Telegram | Use |
|-----------|------------------|-----|
| **INFO**      | Never            | Logs only |
| **IMPORTANT** | Only when *not* in quiet mode | Batched/summary (e.g. stuck recovery attempt, investigation complete) |
| **CRITICAL**  | Always           | Task stuck after max retries, system cannot recover, deployment failed |
| **DEPLOY**    | Always           | Task ready-for-deploy approval (Title, Root cause, Solution, Files changed, Verification, "Do you want to deploy?", Approve / Reject) |

## What is suppressed in quiet mode

- Scheduler activity (no “approval requested” for picking up a task)
- Initial task approval request (scheduler auto-executes instead)
- Stuck recovery attempts (“Task appears stuck… Attempting automatic recovery”)
- Investigation-complete info / approval messages
- Needs-revision / re-investigate messages
- Anomaly detector ops alerts

All of the above remain in **logs**; they are not sent to Telegram.

## What is always sent

### 1. Deploy message (when task reaches ready-for-deploy)

Includes:

- **Title**
- **Root cause**
- **Solution**
- **Files changed**
- **Verification** (test result)
- “Do you want to deploy?”

Buttons: **Approve Deploy**, **Reject**, **Smoke Check**, **View Report**.

### 2. Critical: “Task requires attention”

Sent when:

- Task stuck after max automatic retries (moved to Needs Revision)
- (Future: system cannot recover, deployment failed)

Message: “Task requires attention” with title, status, and that max retries were reached.

## Optional daily summary

Once per day you can send a short summary (tasks completed, in progress, issues).

- Function: `app.services.agent_telegram_policy.send_daily_summary_if_enabled(tasks_completed=0, tasks_in_progress=0, issues=[])`
- In quiet mode this function does **not** send (returns `False`).
- Call from a cron or scheduled job; not called automatically by the agent.

## Example Telegram output in quiet mode

**You will see:**

1. **Deploy approval** (when a patch is ready):

   ```
   🔐 Approval — Patch ready to deploy

   TASK
   Fix orders not syncing in production

   ROOT CAUSE
   ...

   SOLUTION
   ...

   FILES CHANGED
   • backend/app/services/exchange_sync.py

   VERIFICATION
   ✅ 3/3 passed

   Do you want to deploy?
   [Approve Deploy] [Reject] [Smoke Check] [View Report]
   ```

2. **Critical** (when a task needs attention):

   ```
   Task requires attention.

   Title: Fix login timeout
   Status: patching

   Max automatic retries reached; moved to Needs Revision.
   ```

**You will not see:**

- “Agent task approval” (pick-up)
- “Task appears stuck… Attempting automatic recovery”
- “Investigation complete” info
- “Solution verification failed” / Re-investigate
- Anomaly detector ops alerts

## Logging

All existing logs are unchanged. Telegram is not used for logs; quiet mode only gates which **messages** are sent to Telegram.
