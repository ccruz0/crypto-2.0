#!/usr/bin/env python3
"""
Diagnostic script for stuck Notion tasks in the AI Task System.

Reports:
- Tasks by status (pickable vs mid-lifecycle vs terminal)
- Stale tasks (in-progress/investigating older than 30 min)
- Recovery eligibility (would be picked by stale_in_progress playbook)

Run from backend directory with env loaded:
  cd backend && python scripts/diagnose_stuck_notion_tasks.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta

# Ensure backend app is importable
_BACKEND = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# Change to repo root for workspace_root() etc.
_REPO_ROOT = os.path.abspath(os.path.join(_BACKEND, ".."))
os.chdir(_REPO_ROOT)


def _parse_last_edited(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    ts = ts.strip()
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def main() -> None:
    print("=" * 60)
    print("Notion Task System — Stuck Task Diagnostic")
    print("=" * 60)

    api_key = (os.environ.get("NOTION_API_KEY") or "").strip()
    database_id = (os.environ.get("NOTION_TASK_DB") or "").strip()

    if not api_key:
        print("\n[ERROR] NOTION_API_KEY not set. Load .env or set env.")
        return
    if not database_id:
        print("\n[ERROR] NOTION_TASK_DB not set. Load .env or set env.")
        return

    print(f"\nConfig: database_id={database_id[:8]}...")

    try:
        from app.services.notion_task_reader import (
            get_pending_notion_tasks,
            get_tasks_by_status,
            get_raw_status_distribution,
            test_notion_task_scan,
        )
        from app.services.agent_recovery import _investigation_artifacts_exist
    except ImportError as e:
        print(f"\n[ERROR] Import failed: {e}")
        print("Run from backend: cd backend && python scripts/diagnose_stuck_notion_tasks.py")
        return

    # 0. Raw status distribution (diagnostic: exact values Notion stores)
    raw_dist = get_raw_status_distribution(max_pages=50)
    print(f"\n0. Raw Status values in Notion (first 50 pages):")
    if raw_dist.get("ok"):
        for status_val, page_ids in sorted(raw_dist.get("by_status", {}).items()):
            sv = (status_val or "").strip()
            pickable_note = " ← PICKABLE" if sv in ("Planned", "Backlog", "Ready for Investigation", "Blocked") else ""
            print(f"   - {repr(status_val or '(empty)')}: {len(page_ids)} task(s) {pickable_note}")
    else:
        print(f"   Error: {raw_dist.get('error', 'unknown')}")

    # 1. Pickable tasks (what intake sees)
    pickable = get_pending_notion_tasks()
    print(f"\n1. Pickable tasks (planned/backlog/ready-for-investigation/blocked): {len(pickable)}")
    for t in pickable[:10]:
        print(f"   - {t.get('id', '')[:12]}... | {t.get('status', '')} | {t.get('task', '')[:50]}")

    # 2. Mid-lifecycle statuses
    mid_statuses = [
        "in-progress", "In Progress",
        "investigating", "Investigating",
        "ready-for-patch", "Ready for Patch",
        "patching", "Patching",
        "testing", "Testing",
        "deploying", "Deploying",
    ]
    mid_tasks = get_tasks_by_status(mid_statuses, max_results=50)
    print(f"\n2. Mid-lifecycle tasks (in-progress through deploying): {len(mid_tasks)}")

    by_status: dict[str, list] = {}
    for t in mid_tasks:
        s = (t.get("status") or "").strip().lower() or "unknown"
        by_status.setdefault(s, []).append(t)
    for s, tasks in sorted(by_status.items()):
        print(f"   - {s}: {len(tasks)}")

    # 3. Stale analysis (in-progress/investigating > 30 min, no artifact)
    stale_threshold_min = 30
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_threshold_min)
    stale_candidates = []

    for t in mid_tasks:
        status = (t.get("status") or "").strip().lower()
        if status not in ("in-progress", "investigating"):
            continue
        ts = _parse_last_edited(t.get("last_edited_time"))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts > cutoff:
            continue
        tid = str(t.get("id") or "").strip()
        if not tid:
            continue
        has_artifact = _investigation_artifacts_exist(tid)
        stale_candidates.append({
            "id": tid,
            "task": t.get("task", ""),
            "status": status,
            "last_edited": t.get("last_edited_time"),
            "has_artifact": has_artifact,
            "recoverable": not has_artifact,
        })

    print(f"\n3. Stale in-progress/investigating (> {stale_threshold_min} min): {len(stale_candidates)}")
    for c in stale_candidates[:5]:
        rec = "RECOVERABLE (no artifact)" if c["recoverable"] else "has artifact"
        print(f"   - {c['id'][:12]}... | {c['status']} | {c['task'][:40]} | {rec}")

    # 4. Full scan report
    report = test_notion_task_scan()
    print(f"\n4. Full scan: ok={report.get('ok')} tasks_found={report.get('tasks_found', 0)}")
    if report.get("error"):
        print(f"   Error: {report['error']}")

    print("\n" + "=" * 60)
    print("Recovery: AGENT_RECOVERY_ENABLED must be true. Stale in-progress")
    print("playbook runs each scheduler cycle (default: every 5 min).")
    print("=" * 60)


if __name__ == "__main__":
    main()
