"""Sandbox validation for Phase 4B proposals (temp repo copy only; never touches production)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.jarvis.proposals.path_utils import resolve_test_path, rewrite_patch_paths_for_workspace
from app.services._paths import workspace_root

logger = logging.getLogger(__name__)

SANDBOX_BASE = Path(tempfile.gettempdir()) / "jarvis-proposal-sandbox"
DEFAULT_TIMEOUT_SEC = 120


def _run(cmd: list[str], *, cwd: Path, timeout: int = DEFAULT_TIMEOUT_SEC) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def _copy_repo_tree(src: Path, dest: Path) -> None:
    ignore = shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".next", "jarvis-proposal-sandbox", "jarvis-sandbox")
    for item in src.iterdir():
        if item.name in (".git", "node_modules", ".next"):
            continue
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(item, target, ignore=ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def create_proposal_sandbox_workdir(task_id: str) -> Path:
    workdir = SANDBOX_BASE / task_id
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def cleanup_proposal_sandbox(task_id: str) -> None:
    workdir = SANDBOX_BASE / task_id
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)


def validate_patch_in_sandbox(
    *,
    task_id: str,
    patch_content: str,
    test_paths: list[str] | None = None,
    is_noop: bool = False,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """
    Validate a proposal patch in an isolated temp copy of the repo.

    Runs ``git apply --check`` against the patch. Optionally runs pytest on
    ``test_paths`` when the patch check passes.
    """
    root = repo_root or workspace_root()
    result: dict[str, Any] = {
        "task_id": task_id,
        "applicable": False,
        "skipped": False,
        "apply_check_passed": False,
        "tests_ran": False,
        "tests_passed": None,
        "test_paths": list(test_paths or []),
        "workdir": None,
        "error": None,
        "stdout": "",
        "stderr": "",
    }

    if is_noop:
        result["skipped"] = True
        result["applicable"] = False
        result["apply_check_passed"] = None
        return result

    workdir = create_proposal_sandbox_workdir(task_id)
    result["workdir"] = str(workdir)

    try:
        _copy_repo_tree(root, workdir)

        code, _, err = _run(["git", "init"], cwd=workdir)
        if code != 0:
            result["error"] = f"git init failed: {err}"
            return result

        _run(["git", "add", "-A"], cwd=workdir)
        _run(["git", "commit", "-m", "proposal sandbox baseline", "--allow-empty"], cwd=workdir)

        patch_file = workdir / "proposal.patch"
        normalized_patch = rewrite_patch_paths_for_workspace(patch_content, root)
        patch_file.write_text(normalized_patch, encoding="utf-8")

        code, out, err = _run(["git", "apply", "--check", str(patch_file)], cwd=workdir)
        result["stdout"] = out[:2000]
        result["stderr"] = err[:2000]
        if code != 0:
            result["error"] = f"git apply --check failed: {err or out}"
            return result

        result["apply_check_passed"] = True
        result["applicable"] = True

        paths = [p for p in (test_paths or []) if p.strip()]
        if not paths:
            return result

        pytest_targets: list[str] = []
        for rel in paths:
            resolved = resolve_test_path(root, rel)
            if resolved is None:
                result["error"] = f"test path missing in repo: {rel}"
                return result
            try:
                rel_to_workdir = resolved.relative_to(root)
            except ValueError:
                result["error"] = f"test path outside workspace: {resolved}"
                return result
            pytest_targets.append(str(workdir / rel_to_workdir))

        missing = [t for t in pytest_targets if not Path(t).exists()]
        if missing:
            result["error"] = f"test paths missing in sandbox: {missing}"
            return result

        code, out, err = _run(
            ["python3", "-m", "pytest", *pytest_targets, "-q", "--tb=short"],
            cwd=workdir,
            timeout=180,
        )
        result["tests_ran"] = True
        result["tests_passed"] = code == 0
        result["stdout"] = out[:4000]
        result["stderr"] = err[:2000]
        if code != 0:
            result["error"] = f"pytest failed (exit {code})"
        return result

    except Exception as exc:
        logger.exception("proposal sandbox validation failed task_id=%s", task_id)
        result["error"] = str(exc)
        return result
    finally:
        cleanup_proposal_sandbox(task_id)
