#!/usr/bin/env python3
"""
Set Notion task(s) "Investigate Telegram alerts not being sent" (or title containing
"Telegram alerts") from in-progress to done.

Requires NOTION_API_KEY and NOTION_TASK_DB in environment (or .env).
Run from repo root: cd backend && python scripts/set_notion_task_done_telegram_alerts.py
Or from backend: python scripts/set_notion_task_done_telegram_alerts.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    from app.services.notion_task_reader import get_tasks_by_status
    from app.services.notion_tasks import update_notion_task_status

    # Find tasks in status in-progress (try common variants)
    statuses = ["in-progress", "In-Progress", "In Progress"]
    tasks = get_tasks_by_status(statuses, max_results=50)
    # Filter by title containing Telegram
    keyword = "telegram"
    matches = [t for t in tasks if keyword in (t.get("task") or "").lower()]
    if not matches:
        print("No in-progress Notion tasks with 'Telegram' in title found.")
        print(f"Queried statuses: {statuses}; total tasks with those statuses: {len(tasks)}")
        return 1

    comment = "Resolved via script: runbook applied; PROD config correct; status set to done."
    updated = 0
    for t in matches:
        page_id = (t.get("id") or "").strip()
        title = (t.get("task") or "(no title)")[:60]
        if not page_id:
            continue
        ok = update_notion_task_status(page_id, "done", append_comment=comment)
        if ok:
            print(f"Updated to done: {title!r} (id={page_id[:8]}...)")
            updated += 1
        else:
            print(f"Failed to update: {title!r} (id={page_id[:8]}...)")
    print(f"Done. Updated {updated} task(s).")
    return 0 if updated else 1

if __name__ == "__main__":
    sys.exit(main())
