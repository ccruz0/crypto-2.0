"""Isolated sandbox for Phase 5 patch apply (never touches production tree)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.jarvis.change_execution.config import jarvis_sandbox_timeout_sec
from app.jarvis.change_execution.forbidden_paths import (
    check_forbidden_paths,
    task_allows_deployment,
    task_allows_trading,
)
from app.services._paths import workspace_root

logger = logging.getLogger(__name__)

SANDBOX_BASE = Path(tempfile.gettempdir()) / "jarvis-sandbox"


def _run_git(cwd: Path, args: list[str], *, timeout: int | None = None) -> tuple[int, str, str]:
    to = timeout or jarvis_sandbox_timeout_sec()
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=to,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def _branch_name(task_id: str) -> str:
    short = task_id.replace("-", "")[:12]
    return f"jarvis/task-{short}"


def create_sandbox_workdir(task_id: str) -> Path:
    """Create isolated working directory for a task."""
    workdir = SANDBOX_BASE / task_id
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def cleanup_sandbox(task_id: str) -> None:
    workdir = SANDBOX_BASE / task_id
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)


def apply_patch_in_sandbox(
    *,
    task_id: str,
    patch_content: str,
    objective: str = "",
    plan: dict[str, Any] | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """
    Apply approved patch in isolated sandbox:
    1. Clone/copy repo into temp dir
    2. Checkout origin/main
    3. Create jarvis/task-{task_id} branch
    4. Apply patch
    5. Validate forbidden paths
    """
    root = repo_root or workspace_root()
    workdir = create_sandbox_workdir(task_id)
    branch = _branch_name(task_id)
    result: dict[str, Any] = {
        "task_id": task_id,
        "branch_name": branch,
        "workdir": str(workdir),
        "success": False,
        "changed_files": [],
        "forbidden_check": {},
        "error": None,
    }

    try:
        # Initialize bare clone from local repo (no network, isolated copy)
        code, out, err = _run_git(workdir, ["init"])
        if code != 0:
            result["error"] = f"git init failed: {err}"
            return result

        _run_git(workdir, ["remote", "add", "origin", str(root)])

        # Fetch from local origin
        code, out, err = _run_git(workdir, ["fetch", "origin", "--depth=1"])
        if code != 0:
            # Fallback: copy tree if fetch fails (e.g. no remote configured)
            _copy_repo_tree(root, workdir)
            _run_git(workdir, ["add", "-A"])
            _run_git(workdir, ["commit", "-m", "sandbox baseline", "--allow-empty"])
        else:
            # Checkout main or master from origin
            for ref in ("origin/main", "origin/master", "main", "master"):
                code, _, _ = _run_git(workdir, ["checkout", "-B", "main", ref])
                if code == 0:
                    break
            else:
                _copy_repo_tree(root, workdir)
                _run_git(workdir, ["add", "-A"])
                _run_git(workdir, ["commit", "-m", "sandbox baseline", "--allow-empty"])

        # Block push to main — create task branch from current HEAD
        code, _, err = _run_git(workdir, ["checkout", "-B", branch])
        if code != 0:
            result["error"] = f"branch creation failed: {err}"
            return result

        # Write patch to temp file and apply
        patch_file = workdir / "approved.patch"
        patch_file.write_text(patch_content, encoding="utf-8")
        code, out, err = _run_git(workdir, ["apply", "--check", str(patch_file)])
        if code != 0:
            result["error"] = f"patch check failed: {err or out}"
            return result

        code, out, err = _run_git(workdir, ["apply", str(patch_file)])
        if code != 0:
            result["error"] = f"patch apply failed: {err or out}"
            return result

        # Collect changed files
        code, out, _ = _run_git(workdir, ["diff", "--name-only", "HEAD"])
        changed = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if not changed:
            code, out, _ = _run_git(workdir, ["status", "--porcelain"])
            changed = []
            for line in out.splitlines():
                if len(line) >= 4:
                    changed.append(line[3:].strip())

        result["changed_files"] = changed

        # Forbidden path check
        forbidden = check_forbidden_paths(
            changed,
            allow_trading=task_allows_trading(objective, plan),
            allow_deployment=task_allows_deployment(objective, plan),
        )
        result["forbidden_check"] = forbidden
        if not forbidden["passed"]:
            result["error"] = f"forbidden paths touched: {forbidden['blocked_paths']}"
            return result

        # Save applied patch diff artifact
        code, diff_out, _ = _run_git(workdir, ["diff", "HEAD"])
        applied_patch_path = workdir / "applied_patch.diff"
        applied_patch_path.write_text(diff_out or patch_content, encoding="utf-8")

        changed_files_path = workdir / "changed_files.json"
        changed_files_path.write_text(json.dumps(changed, indent=2), encoding="utf-8")

        result["success"] = True
        result["applied_patch_path"] = str(applied_patch_path)
        result["changed_files_path"] = str(changed_files_path)
        return result

    except Exception as exc:
        logger.exception("sandbox apply failed task_id=%s", task_id)
        result["error"] = str(exc)
        return result


def _copy_repo_tree(src: Path, dest: Path) -> None:
    """Copy repo tree excluding .git and sandbox dirs."""
    ignore = shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".next", "jarvis-sandbox")
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


def validate_clean_worktree(workdir: Path) -> dict[str, Any]:
    """Validate sandbox worktree is in expected state."""
    code, out, err = _run_git(workdir, ["status", "--porcelain"])
    return {
        "clean": code == 0 and not out.strip(),
        "status_output": out.strip()[:500],
        "error": err if code != 0 else None,
    }


def block_push_to_main(branch: str, remote_ref: str = "") -> bool:
    """Return True if push would be blocked (push to main/master forbidden)."""
    blocked_refs = {"main", "master", "origin/main", "origin/master"}
    if branch.strip().lower() in blocked_refs:
        return True
    if remote_ref and remote_ref.strip().lower() in blocked_refs:
        return True
    return False
