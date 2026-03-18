#!/usr/bin/env python3
"""
Diagnostic: trace execution_mode from Notion through the pipeline.

Usage:
  python -m app.scripts.diag.diagnose_execution_mode <task_id>
  # or from backend/:
  python scripts/diag/diagnose_execution_mode.py <task_id>

Prints:
  - Raw Notion property for Execution Mode
  - Parsed task execution_mode
  - Whether strict mode would be active
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure backend is on path
_backend = Path(__file__).resolve().parents[2]
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))


def main() -> int:
    task_id = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not task_id:
        print("Usage: python -m app.scripts.diag.diagnose_execution_mode <task_id>")
        return 1

    from app.services.notion_task_reader import (
        get_notion_task_by_id,
        _extract_execution_mode_raw,
        _parse_page,
    )
    from app.services.notion_task_reader import _get_config
    import httpx

    api_key, database_id = _get_config()
    if not api_key:
        print("ERROR: NOTION_API_KEY not set")
        return 1

    # Fetch raw page from Notion API to see full structure
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"https://api.notion.com/v1/pages/{task_id}",
                headers=headers,
            )
    except Exception as e:
        print(f"ERROR: Failed to fetch page: {e}")
        return 1

    if resp.status_code != 200:
        print(f"ERROR: Notion API returned {resp.status_code}: {resp.text[:500]}")
        return 1

    page = resp.json()
    props = page.get("properties") or {}

    print("=" * 60)
    print("EXECUTION MODE DIAGNOSTIC")
    print("=" * 60)
    print(f"Task ID: {task_id}")
    print()

    # 1. Raw property payload
    for name in ("Execution Mode", "execution_mode", "ExecutionMode"):
        if name in props:
            val = props[name]
            print(f"Raw property '{name}':")
            print(json.dumps(val, indent=2, default=str))
            print()
            break
    else:
        print("Execution Mode property: NOT FOUND")
        print("Properties containing 'exec' or 'mode':")
        for k in props:
            if "exec" in k.lower() or "mode" in k.lower():
                print(f"  - {k}: {json.dumps(props[k], default=str)[:200]}")
        print()
        print("All property keys:", list(props.keys()))
        print()

    # 2. Parsed value
    raw_summary = _extract_execution_mode_raw(props)
    print(f"Extracted (raw summary): {raw_summary}")
    print()

    # 3. Full parsed task
    parsed = _parse_page(page)
    exec_mode = parsed.get("execution_mode", "?")
    print(f"Parsed task execution_mode: {exec_mode}")
    print()
    if exec_mode == "strict":
        print(">>> STRICT MODE WOULD BE ACTIVE <<<")
    else:
        print(">>> Normal mode (strict would NOT be active) <<<")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
