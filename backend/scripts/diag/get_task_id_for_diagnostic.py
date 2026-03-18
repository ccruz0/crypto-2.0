#!/usr/bin/env python3
"""
Extract a Notion task ID for use with diagnose_execution_mode.py.

Sources (in order):
1. First planned task from Notion (if API configured)
2. Most recent artifact in docs/agents/bug-investigations
3. Fallback: known IDs from repo

Usage:
  python scripts/diag/get_task_id_for_diagnostic.py
  # or with venv:
  .venv/bin/python backend/scripts/diag/get_task_id_for_diagnostic.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure backend is on path
_backend = Path(__file__).resolve().parents[2]
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))


def main() -> int:
    task_id = None
    source = ""

    # 1. Try first planned task from Notion
    try:
        from app.services.notion_task_reader import get_pending_notion_tasks

        tasks = get_pending_notion_tasks()
        if tasks:
            task_id = str(tasks[0].get("id") or "").strip()
            if task_id:
                source = "first_notion_planned"
    except Exception as e:
        pass  # Notion not configured or failed

    # 2. Try most recent artifact
    if not task_id:
        root = _backend.parent if (_backend / "app").exists() else _backend
        for subdir in ("docs/agents/bug-investigations", "docs/agents/telegram-alerts", "docs/agents/execution-state", "docs/runbooks/triage"):
            d = root / subdir
            if not d.exists():
                continue
            for f in sorted(d.glob("notion-*-*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
                m = re.search(r"notion-(?:bug|telegram|execution|triage)-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.md", f.name, re.I)
                if m:
                    task_id = m.group(1)
                    source = f"artifact:{f.name}"
                    break
            if task_id:
                break

    # 3. Fallback: known IDs from repo
    if not task_id:
        task_id = "4d7d1312-8ece-4fcb-b092-ef437c09ee2c"
        source = "fallback_known"

    print(task_id)
    if not sys.stdout.isatty():
        print(f"# source: {source}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
