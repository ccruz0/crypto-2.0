"""Read-only repository inspection tool."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services._paths import workspace_root


def inspect_repository(*, path: str = ".") -> dict[str, Any]:
    repo_root = workspace_root()
    target = (repo_root / path).resolve()
    if not str(target).startswith(str(repo_root)):
        return {"tool": "inspect_repository", "error": "path outside repository", "read_only": True}

    git_status = ""
    git_head = ""
    try:
        git_status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
        git_head = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass

    top_dirs = sorted(
        [
            p.name
            for p in repo_root.iterdir()
            if p.is_dir() and p.name not in {"proc", "sys", "dev", "run"}
        ]
    )[:20]
    return {
        "tool": "inspect_repository",
        "repo_root": str(repo_root),
        "git_head": git_head,
        "dirty_files": git_status.splitlines()[:20] if git_status else [],
        "top_level_dirs": top_dirs,
        "read_only": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
