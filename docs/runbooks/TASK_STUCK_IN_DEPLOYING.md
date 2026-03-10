# Task stuck in "deploying"

A task can stay in **deploying** until something runs the post-deploy smoke check and updates Notion to **done** or **blocked**.

## How it gets out of "deploying"

| Path | When |
|------|------|
| **GitHub webhook** | When the deploy workflow run **completes**, GitHub sends `workflow_run` to the backend. Backend runs smoke check and moves the task to done/blocked. |
| **Manual: Smoke Check button** | In Telegram, on the approval card for that task, tap **Smoke Check**. Backend runs the check and updates the task. |
| **Recovery playbook** | If `AGENT_RECOVERY_ENABLED` is true, the scheduler runs an "orphan smoke" playbook. Tasks in **deploying** for **>10 minutes** get one automatic smoke check. |

If the webhook never reaches the backend (URL not configured, backend not reachable from GitHub, or wrong secret), the task will stay in **deploying** until you run Smoke Check or recovery runs.

## What to do now

1. **Unblock immediately:** In Telegram, open the approval for that task and tap **Smoke Check**. The backend will run the health check and set the task to **done** or **blocked**.
2. **Optional:** In Notion, check the task’s activity log for `webhook_smoke_check` or `recovery_orphan_smoke_attempt` to see if the webhook or recovery already ran.
3. **Long-term:** To have tasks clear automatically after deploy, ensure the GitHub Actions deploy workflow sends `workflow_run` events to your backend (e.g. `POST .../api/github/actions`) and that `GITHUB_WEBHOOK_SECRET` is set and the backend URL is reachable from GitHub.
