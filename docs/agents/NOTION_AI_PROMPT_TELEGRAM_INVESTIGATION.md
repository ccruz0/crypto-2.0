# Notion AI prompt: Create task to investigate Telegram failure

Copy the block below and paste it into **Notion AI** (e.g. in the AI Task System database or a page that creates tasks there). Notion AI will create a new task with the right properties for the backend and agents to pick up.

---

## Prompt to paste into Notion AI

```
In the AI Task System database, create a new task with these properties:

- **Task (title):** Investigate Telegram failure

- **Project:** Infrastructure (or Monitoring)

- **Type:** monitoring

- **Status:** planned (or ready-for-investigation)

- **Priority:** high

- **Source:** openclaw (or manual)

- **Details:** Telegram is failing on the Automated Trading Platform. Please open an investigation task to:
  1. Run the Telegram diagnostic (see runbook docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md): from PROD run `docker compose --profile aws exec backend-aws python scripts/diagnose_telegram_alerts.py` or from Mac run `./scripts/diag/run_telegram_diagnostic_prod.sh`.
  2. Check block reasons: RUN_TELEGRAM, kill switch (tg_enabled_aws), TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (or _AWS variants), and RUNTIME_ORIGIN so that AWS services send to Telegram.
  3. Verify secrets/runtime.env and .env.aws have the correct Telegram vars; ensure backend and market-updater-aws can read runtime.env (permissions).
  4. Document findings and apply fixes; update this task status when done.

Use exact property names: Task, Project, Type, Status, Priority, Source, Details. If a property already exists in the database, use it; do not duplicate.
```

---

## Short version (minimal prompt)

If your Notion AI works better with a shorter instruction:

```
Create a new task in the AI Task System:

Title: Investigate Telegram failure
Project: Infrastructure
Type: monitoring
Status: planned
Priority: high
Details: Telegram is failing. Follow runbook docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md: run diagnose_telegram_alerts.py on PROD (or run_telegram_diagnostic_prod.sh from Mac), check RUN_TELEGRAM, token/chat_id, kill switch, and runtime.env permissions. Fix and document.
```

---

## After the task is created

- The backend / OpenClaw can read it via `get_pending_notion_tasks()` or `get_high_priority_pending_tasks()`.
- Runbook: [TELEGRAM_ALERTS_NOT_SENT.md](../runbooks/TELEGRAM_ALERTS_NOT_SENT.md).
- Optional: run diagnostic from your machine: `./scripts/diag/run_telegram_diagnostic_prod.sh`.
