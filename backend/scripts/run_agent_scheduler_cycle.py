#!/usr/bin/env python3
"""
Run one agent scheduler cycle: prepare at most one task, then either send
approval request to Telegram or auto-execute low-risk tasks.

Usage:
  python backend/scripts/run_agent_scheduler_cycle.py
  TASK_ID=31db1837-03fe-80ca-89a5-c71bfbdbfc78 python backend/scripts/run_agent_scheduler_cycle.py  # specific task

Requires NOTION_API_KEY, NOTION_TASK_DB for preparation; TELEGRAM_* for approval requests.
Exit code: 0 on success (including no task / skipped), 1 on failure.
"""

import json
import os
import sys
from pathlib import Path

# Add backend to path so "app" is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.agent_scheduler import run_agent_scheduler_cycle


def main() -> int:
    task_id = (os.environ.get("TASK_ID") or "").strip() or None
    result = run_agent_scheduler_cycle(task_id=task_id)
    ok = result.get("ok", False)
    action = result.get("action", "none")
    print(json.dumps(result, default=str, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
