# Deploy progress bar in Notion

When a task is in **deploying**, the backend can update a **Deploy Progress** property (0–100) on the Notion task page so you see a completion bar next to the task while deploy and smoke check run.

## Setup (one-time)

1. Open your **AI Task System** (or equivalent) Notion database.
2. Add a new property:
   - **Name:** `Deploy Progress` (exact spelling).
   - **Type:** Number.
   - **Range:** 0–100 (no decimals).
3. In Notion, set the property display to **Progress** so it shows as a bar (if your Notion plan supports it). Otherwise it will show as a number (e.g. 45).

The backend writes this property only when a task is in **deploying**; if the property is missing, updates are skipped and no error is raised.

## When the bar updates

| Progress | Moment |
|----------|--------|
| 0% | Task status set to **deploying** (e.g. deploy approved in Telegram). |
| 20% | Deploy workflow triggered (GitHub Actions dispatch) or deploy step completed in executor. |
| 30% | Smoke check started (waiting for backend). |
| 35% | Initial delay finished; liveness check starting. |
| 55% | Liveness check passed. |
| 85% | System health check passed. |
| 100% | Smoke check finished (passed or failed); task moves to **done** or **blocked**. |

If any step fails, progress is set to 100% when the run finishes so the bar reflects completion.

## Code

- **Write:** `notion_tasks.update_notion_deploy_progress(page_id, percent)` (best-effort; never raises).
- **Constant:** `notion_tasks.DEPLOY_PROGRESS_PROPERTY` = `"Deploy Progress"`.
