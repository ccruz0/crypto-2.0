"""Test execution agent for Jarvis Phase 4 (local only, timeout protected)."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services._paths import workspace_root

_DEFAULT_TIMEOUT_SEC = 120


def _repo_root() -> Path:
    root = workspace_root()
    if (root / "tests").is_dir():
        return root
    if (root.parent / "backend" / "tests").is_dir():
        return root.parent
    return root


def _tests_dir() -> Path:
    root = _repo_root()
    if (root / "backend" / "tests").is_dir():
        return root / "backend" / "tests"
    return root / "tests"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_production_env() -> bool:
    env = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "").lower()
    return env in {"production", "prod"}


def determine_relevant_tests(
    *,
    changed_files: list[str] | None = None,
    objective: str = "",
) -> list[str]:
    """Map changed files / objective keywords to pytest node ids."""
    repo_root = _repo_root()
    tests_dir = _tests_dir()
    if not tests_dir.is_dir():
        return []

    candidates: list[str] = []
    objective_l = objective.lower()
    keyword_map = {
        "jarvis": "test_jarvis",
        "patch": "test_patch",
        "review": "test_reviewer",
        "repository": "test_repository",
        "websocket": "websocket",
        "openclaw": "openclaw",
        "deploy": "deploy",
        "routes_jarvis": "routes_jarvis",
    }
    for keyword, pattern in keyword_map.items():
        if keyword in objective_l or any(pattern in (f or "") for f in (changed_files or [])):
            candidates.append(pattern)

    selected: list[str] = []
    for path in sorted(tests_dir.glob("test_*.py")):
        rel = str(path.relative_to(repo_root))
        name = path.name.lower()
        if not candidates or any(c.lower() in name or c.lower() in rel.lower() for c in candidates):
            selected.append(rel)
    if not selected and candidates:
        for path in sorted(tests_dir.glob("**/test_*.py")):
            rel = str(path.relative_to(repo_root))
            if any(c.lower() in rel.lower() for c in candidates):
                selected.append(rel)
    if not selected:
        for candidate in (tests_dir / "test_jarvis_execution_phase3.py", repo_root / "backend" / "tests" / "test_jarvis_execution_phase3.py"):
            if candidate.is_file():
                return [str(candidate.relative_to(repo_root))]
        all_tests = sorted(tests_dir.glob("test_*.py"))
        if all_tests:
            return [str(all_tests[0].relative_to(repo_root))]
        return []
    return selected[:10]


def run_selected_tests(
    test_paths: list[str],
    *,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run pytest on selected tests locally (never in production)."""
    if _is_production_env():
        return {
            "ok": False,
            "error": "test execution forbidden in production",
            "execution_log": "blocked: production environment",
            "read_only": True,
            "local_only": True,
        }

    repo_root = _repo_root()
    started = _now_iso()
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "selected_tests": test_paths,
            "passed_count": 0,
            "failed_count": 0,
            "failing_tests": [],
            "execution_log": f"dry-run: would execute {len(test_paths)} test file(s)",
            "started_at": started,
            "completed_at": _now_iso(),
            "local_only": True,
        }

    cmd = ["python3", "-m", "pytest", *test_paths, "-q", "--tb=short", "--no-header"]
    log_lines: list[str] = [f"$ {' '.join(cmd)}"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=max(10, min(timeout_sec, 300)),
            check=False,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        log_lines.extend(stdout.splitlines()[-50:])
        if stderr:
            log_lines.append("--- stderr ---")
            log_lines.extend(stderr.splitlines()[-20:])
        failing = [line for line in stdout.splitlines() if " FAILED " in line or line.startswith("FAILED")]
        passed_lines = [line for line in stdout.splitlines() if line.strip().endswith(" PASSED")]
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "selected_tests": test_paths,
            "passed_count": len(passed_lines),
            "failed_count": len(failing),
            "failing_tests": failing[:20],
            "execution_log": "\n".join(log_lines),
            "started_at": started,
            "completed_at": _now_iso(),
            "local_only": True,
            "timeout_sec": timeout_sec,
        }
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"").decode("utf-8", errors="ignore") if exc.stdout else ""
        return {
            "ok": False,
            "error": f"timeout after {timeout_sec}s",
            "selected_tests": test_paths,
            "failing_tests": ["TIMEOUT"],
            "execution_log": partial + f"\nTIMEOUT after {timeout_sec}s",
            "started_at": started,
            "completed_at": _now_iso(),
            "local_only": True,
        }


def run_tests_for_patch(
    *,
    patch: dict[str, Any],
    objective: str = "",
    dry_run: bool = True,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Determine and run tests relevant to a patch."""
    tests = determine_relevant_tests(changed_files=patch.get("target_files"), objective=objective or patch.get("objective", ""))
    results = run_selected_tests(tests, timeout_sec=timeout_sec, dry_run=dry_run)
    return {
        "agent": "test_agent",
        "test_report": results,
        "selected_tests": tests,
        "summary": _summarize(results),
        "created_at": _now_iso(),
        "read_only": True,
    }


def _summarize(results: dict[str, Any]) -> str:
    if results.get("dry_run"):
        return f"Dry-run: {len(results.get('selected_tests', []))} test file(s) selected"
    if not results.get("ok"):
        return f"Failed: {results.get('failed_count', 0)} test(s), error={results.get('error', 'see log')}"
    return f"Passed: {results.get('passed_count', 0)} test(s)"
