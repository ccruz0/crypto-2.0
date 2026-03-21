#!/usr/bin/env python3
"""
Validation script for Telegram task deduplication and merge behavior.

Run from backend/: PYTHONPATH=. python scripts/validate_telegram_task_dedup.py

Checks:
1. Unit tests pass
2. create_task_from_telegram_intent merges input when similar task found
3. append_telegram_input_to_task respects dry-run
4. Telegram response includes input_merged
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch


def run_tests() -> bool:
    """Run task compiler and value gate tests."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_task_compiler_similarity.py", "tests/test_task_value_gate.py", "-v", "-q"],
        cwd=".",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("FAIL: Unit tests failed")
        print(result.stdout)
        print(result.stderr)
        return False
    print("PASS: Unit tests")
    return True


def test_merge_flow() -> bool:
    """Verify merge flow: similar task found -> append called -> input_merged in result."""
    from app.services.task_compiler import create_task_from_telegram_intent

    similar_task = {
        "id": "test-page-id",
        "task": "Fix purchase_price discrepancy",
        "status": "needs-revision",
        "type": "Bug",
    }
    with (
        patch("app.services.task_compiler.append_telegram_input_to_task", return_value=True),
        patch("app.services.task_compiler.update_notion_task_priority", return_value=True),
        patch("app.services.task_compiler.update_notion_task_status"),
        patch("app.services.task_compiler.create_notion_task"),
        patch("app.services.task_compiler.find_similar_task", return_value=similar_task),
        patch("app.services.task_compiler.notion_is_configured", return_value=True),
    ):
        result = create_task_from_telegram_intent("fix purchase_price across trading system", "Carlos")
        if not result.get("ok"):
            print("FAIL: create_task_from_telegram_intent returned ok=False")
            return False
        if not result.get("reused"):
            print("FAIL: reused should be True when similar task found")
            return False
        if not result.get("input_merged"):
            print("FAIL: input_merged should be True when append succeeds")
            return False
        print("PASS: Merge flow (similar task -> append -> input_merged=True)")
        return True


def test_dry_run_skip() -> bool:
    """Verify append_telegram_input_to_task returns True without API call when dry-run."""
    import os
    from app.services.notion_tasks import append_telegram_input_to_task

    orig = os.environ.get("NOTION_DRY_RUN")
    try:
        os.environ["NOTION_DRY_RUN"] = "1"
        # With dry-run, should return True even without real Notion
        ok = append_telegram_input_to_task("fake-page-id", "test intent", "Carlos")
        if not ok:
            print("FAIL: append_telegram_input_to_task should return True in dry-run")
            return False
        print("PASS: Dry-run skips Notion API")
        return True
    finally:
        if orig is not None:
            os.environ["NOTION_DRY_RUN"] = orig
        elif "NOTION_DRY_RUN" in os.environ:
            del os.environ["NOTION_DRY_RUN"]


def main() -> int:
    print("=== Telegram Task Dedup Validation ===\n")
    checks = [
        ("Unit tests", run_tests),
        ("Merge flow", test_merge_flow),
        ("Dry-run skip", test_dry_run_skip),
    ]
    failed = 0
    for name, fn in checks:
        try:
            if not fn():
                failed += 1
        except Exception as e:
            print(f"FAIL: {name} raised {e}")
            failed += 1
    print()
    if failed:
        print(f"Validation failed: {failed} check(s)")
        return 1
    print("All validation checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
