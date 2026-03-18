# Notion AI Task System — Select options (display names)

Notion requires **Select** option names to be human-readable and to start with a capital letter. The backend uses internal values (lowercase, hyphenated). It **maps** between the two:

- **When reading:** Notion returns e.g. `"Ready for Patch"` → backend normalises to `ready-for-patch`.
- **When writing:** Backend sends the **display name** (e.g. `"Ready for Patch"`) so the Select option exists in Notion.

So you can keep **Type**, **Status**, and **Priority** as **Select** and use the option names below. The backend will work with them.

---

## Status (Select) — use these option names exactly

Create one Select option per line; names must match exactly (capitalisation and spaces):

- Planned  
- In Progress  
- Investigating  
- Investigation Complete  
- Ready for Patch  
- Patching  
- Testing  
- Awaiting Deploy Approval  
- Deploying  
- Done  
- Blocked  
- Rejected  
- Needs Revision  
- Backlog  
- Ready for Investigation  
- Deployed  

---

## Type (Select) — recommended options

Backend normalises to lowercase for matching (e.g. `Bug` → `bug`). Use any human-readable labels; these are suggested:

- Bug  
- Bugfix  
- Monitoring  
- Improvement  
- Strategy  
- Automation  
- Infrastructure  

---

## Priority (Select)

Backend normalises to lowercase. Suggested options:

- Critical  
- High  
- Medium  
- Low  

---

## Notion AI prompt (copy-paste)

Paste this into **Notion AI** in your AI Task System database to add or align properties and **Status** Select options:

```
In the database **AI Task System**, add or align these properties with **these exact names** (in English). If a property already exists, do not duplicate it.

- **Task** — Title or Text (short task title).
- **Type** — Select. Add these options if missing: Bug, Bugfix, Monitoring, Improvement, Strategy, Automation, Infrastructure.
- **Status** — Select. Add exactly these options (capitalisation and spacing as written): Planned, In Progress, Investigating, Investigation Complete, Ready for Patch, Patching, Testing, Awaiting Deploy Approval, Deploying, Done, Blocked, Rejected, Needs Revision, Backlog, Ready for Investigation, Deployed.
- **Project** — Text or Select (e.g. Automation, Docs, Infrastructure).
- **Details** — Rich text (full description).
- **Priority** — Select. Add options: Critical, High, Medium, Low.
- **Source** — Text (e.g. openclaw, monitoring).
- **Execution Mode** — Select (optional). Options: Normal, Strict. When Strict, OpenClaw blocks ready-for-patch until proof criteria are met.
- **GitHub Link** — URL (optional).
- **Test Status** — Text (written by backend).
- **Deploy Progress** — Number, 0–100 (optional).
- **Cursor Patch URL** — URL (optional; written by backend).

Do not create Status options in lowercase or with hyphens (e.g. not "ready-for-patch"); use the human-readable form above (e.g. "Ready for Patch"). Keep all property names exactly as written.
```

---

## Reference

Mapping is implemented in:

- `backend/app/services/notion_tasks.py`: `NOTION_STATUS_INTERNAL_TO_DISPLAY`, `notion_status_to_display`, `notion_status_from_display`
- `backend/app/services/notion_task_reader.py`: `_normalize_status_from_notion()` so parsed tasks always have internal status in `task["status"]`
