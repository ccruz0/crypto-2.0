#!/usr/bin/env python3
"""
Run post-deploy smoke check for the task currently in "deploying".
Use on the backend server (or with NOTION_API_KEY, NOTION_TASK_DB, ATP_HEALTH_BASE set).
Optional: pass task_id as first arg; otherwise uses first task in deploying.
"""
from __future__ import annotations

import os
import sys

# Allow importing app when run from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main() -> None:
    task_id = (sys.argv[1] or "").strip() if len(sys.argv) > 1 else ""
    if not task_id:
        from app.services.notion_task_reader import get_tasks_by_status
        tasks = get_tasks_by_status(["deploying", "Deploying"], max_results=1)
        if not tasks:
            print("No task in deploying status.")
            sys.exit(1)
        task_id = str(tasks[0].get("id") or "").strip()
        if not task_id:
            print("Could not get task id from deploying task.")
            sys.exit(1)
        print(f"Using first deploying task: {task_id[:12]}...")

    from app.services.deploy_smoke_check import run_and_record_smoke_check
    result = run_and_record_smoke_check(
        task_id,
        advance_on_pass=True,
        current_status="deploying",
    )
    outcome = result.get("outcome", "unknown")
    advanced = result.get("advanced", False)
    blocked = result.get("blocked", False)
    print(f"Outcome: {outcome}")
    print(f"Advanced to done: {advanced}")
    print(f"Marked blocked: {blocked}")
    print(result.get("summary", ""))

if __name__ == "__main__":
    main()
