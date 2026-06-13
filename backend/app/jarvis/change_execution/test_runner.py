"""Post-apply test runner for Phase 5 sandbox validation."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.jarvis.agents.test_agent import determine_relevant_tests, run_tests_for_patch
from app.jarvis.change_execution.config import jarvis_test_timeout_sec
from app.jarvis.change_execution.sandbox import validate_clean_worktree
from app.services._paths import workspace_root

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_frontend_touched(changed_files: list[str]) -> bool:
    return any(
        f.startswith("frontend/") or "/frontend/" in f or f.endswith((".tsx", ".jsx", ".css"))
        for f in changed_files
    )


def _run_frontend_build(*, cwd: Path, timeout: int) -> dict[str, Any]:
    frontend_dir = cwd / "frontend"
    if not frontend_dir.is_dir():
        root = workspace_root()
        frontend_dir = root / "frontend"
    if not (frontend_dir / "package.json").is_file():
        return {"skipped": True, "reason": "frontend/package.json not found"}

    try:
        proc = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "CI": "true"},
        )
        return {
            "skipped": False,
            "passed": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
            "command": "npm run build",
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"skipped": False, "passed": False, "error": str(exc), "command": "npm run build"}


def run_sandbox_tests(
    *,
    task_id: str,
    workdir: Path,
    changed_files: list[str],
    objective: str,
    patch: dict[str, Any] | None = None,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Run affected backend tests + optional frontend build after patch apply."""
    timeout = timeout_sec or jarvis_test_timeout_sec()
    started = _now_iso()

    patch_stub = patch or {"files_affected": changed_files, "unified_diff": ""}
    backend_result = run_tests_for_patch(
        patch=patch_stub,
        objective=objective,
        dry_run=False,
        timeout_sec=timeout,
    )
    test_report = backend_result.get("test_report") or {}
    backend_passed = test_report.get("ok", backend_result.get("passed", False))

    frontend_result: dict[str, Any] = {"skipped": True}
    if _is_frontend_touched(changed_files):
        frontend_result = _run_frontend_build(cwd=workdir, timeout=timeout)

    worktree_validation = validate_clean_worktree(workdir)
    relevant_tests = determine_relevant_tests(changed_files=changed_files, objective=objective)

    all_passed = backend_passed and (
        frontend_result.get("skipped") or frontend_result.get("passed", False)
    )

    result = {
        "task_id": task_id,
        "started_at": started,
        "completed_at": _now_iso(),
        "passed": all_passed,
        "backend_tests": test_report,
        "backend_summary": backend_result.get("summary", ""),
        "frontend_build": frontend_result,
        "worktree_validation": worktree_validation,
        "relevant_tests": relevant_tests,
        "changed_files": changed_files,
        "timeout_sec": timeout,
    }
    return result


def write_test_artifacts(workdir: Path, test_results: dict[str, Any]) -> dict[str, str]:
    """Write test_results.json and validation_report.md to workdir."""
    results_path = workdir / "test_results.json"
    results_path.write_text(json.dumps(test_results, indent=2, default=str), encoding="utf-8")

    report_lines = [
        "# Phase 5 Validation Report",
        "",
        f"**Task ID:** {test_results.get('task_id', 'unknown')}",
        f"**Passed:** {test_results.get('passed', False)}",
        f"**Started:** {test_results.get('started_at', '')}",
        f"**Completed:** {test_results.get('completed_at', '')}",
        "",
        "## Backend Tests",
        f"- Summary: {test_results.get('backend_summary', 'N/A')}",
        f"- Passed: {test_results.get('backend_tests', {}).get('passed', 'N/A')}",
        "",
        "## Frontend Build",
        f"- Skipped: {test_results.get('frontend_build', {}).get('skipped', True)}",
        f"- Passed: {test_results.get('frontend_build', {}).get('passed', 'N/A')}",
        "",
        "## Worktree Validation",
        f"- Clean: {test_results.get('worktree_validation', {}).get('clean', False)}",
        "",
        "## Changed Files",
    ]
    for f in test_results.get("changed_files") or []:
        report_lines.append(f"- `{f}`")

    report_path = workdir / "validation_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    return {
        "test_results.json": str(results_path),
        "validation_report.md": str(report_path),
    }
