# Release Changelog

Tracks OpenClaw business-logic proposal/approval/release traceability.

## Notion Fields Required For Full Version Traceability

- `Current Version` (text/select)
- `Proposed Version` (text/select)
- `Approved Version` (text/select, optional but recommended)
- `Released Version` (text/select)
- `Version Status` (select preferred: `proposed`, `approved`, `released`, `rejected`)
- `Change Summary` (text)

## v0.1.0 - 2026-03-07

- Version: `v0.1.0`
- Date: `2026-03-07`
- Task ID: `implementation-bootstrap`
- Summary: Added explicit version metadata flow across task preparation, approval, execution, Notion updates, Telegram visibility, and activity events.
- Affected files:
  - `backend/app/services/agent_versioning.py`
  - `backend/app/services/agent_task_executor.py`
  - `backend/app/services/agent_telegram_approval.py`
  - `backend/app/services/notion_tasks.py`
  - `backend/app/services/notion_task_reader.py`
- Validation note: Static checks and lint review on modified Python/docs files.
## v0.1.1 - 2026-03-30

- Version: `v0.1.1`
- Date: `2026-03-30`
- Task ID: `333b1837-03fe-8169-bb4f-fc592431920a`
- Summary: [Anomaly] Scheduler Inactivity in Monitoring / Infrastructure; validation=OpenClaw investigation validated (5 sections, 1425 chars); deployment=not run
- Affected files: see task proposal metadata in Notion/agent activity log.
- Validation note: recorded in task execution summary and Notion release comment.

## v0.1.1 - 2026-03-30

- Version: `v0.1.1`
- Date: `2026-03-30`
- Task ID: `333b1837-03fe-81ae-8ed5-c101a996c7f7`
- Summary: [Anomaly] Scheduler Inactivity in Monitoring / Infrastructure; validation=OpenClaw investigation validated (5 sections, 1425 chars); deployment=not run
- Affected files: see task proposal metadata in Notion/agent activity log.
- Validation note: recorded in task execution summary and Notion release comment.

