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
