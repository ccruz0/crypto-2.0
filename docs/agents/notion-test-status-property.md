# Test Status property in Notion

The deploy approval flow uses a **Test Status** property on the AI Task System database to decide whether tests passed before allowing deploy. If the property is missing, the backend falls back to the task’s **Status** (e.g. `awaiting-deploy-approval`) and appends a short note to the task.

To have test results stored in Notion and to avoid the fallback message, add the property once.

## Setup (one-time)

1. Open your **AI Task System** Notion database.
2. Add a new property:
   - **Name:** `Test Status` (exact spelling; the backend expects this label).
   - **Type:** **Text** or **Rich text** (recommended), or **Select** with options like `passed`, `failed`, `not run`, `partial`.
3. Save. You can leave it empty for existing tasks; the backend will fill it when tests run.

## What the backend does

- **Read:** When you approve deploy in Telegram, the backend reads `Test Status` to decide if tests passed. If the property is absent or empty and the task is in `awaiting-deploy-approval`, it allows deploy and adds a note that it used task status as the gate.
- **Write:** After tests run (e.g. Cursor bridge, validation), the backend writes the outcome to `Test Status` via `update_notion_task_metadata` (e.g. `passed: …`, `failed: …`). If the property doesn’t exist, the write is skipped and the deploy gate uses the fallback above.

## After adding the property

- New test runs will persist in **Test Status**.
- Deploy approval comments will refer to the stored value (e.g. “tests passed (…)”) instead of the fallback message.
- The deploy gate will use **Test Status** when present, and only use task status when **Test Status** is empty or missing.
