"""Read-only GitHub integration for Jarvis Phase 4."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def _git(args: list[str], *, timeout: int = 15) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def inspect_branches(*, limit: int = 20) -> dict[str, Any]:
    code, out, err = _git(["branch", "-a", "--format=%(refname:short)|%(committerdate:iso8601)|%(objectname:short)"])
    branches: list[dict[str, str]] = []
    for line in out.splitlines()[:limit]:
        parts = line.split("|")
        if parts:
            branches.append({"name": parts[0], "updated": parts[1] if len(parts) > 1 else "", "sha": parts[2] if len(parts) > 2 else ""})
    return {"branches": branches, "read_only": True, "error": err if code != 0 else None}


def inspect_recent_commits(*, limit: int = 15) -> dict[str, Any]:
    code, out, err = _git(
        ["log", f"-{limit}", "--pretty=format:%H|%an|%ae|%s|%ci"]
    )
    commits: list[dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("|", 4)
        if len(parts) >= 5:
            commits.append({"sha": parts[0], "author": parts[1], "email": parts[2], "message": parts[3], "date": parts[4]})
    return {"commits": commits, "read_only": True, "error": err if code != 0 else None}


def inspect_workflows(*, repo_root: str | None = None) -> dict[str, Any]:
    root = repo_root or os.getcwd()
    wf_dir = os.path.join(root, ".github", "workflows")
    workflows: list[dict[str, str]] = []
    if os.path.isdir(wf_dir):
        for name in sorted(os.listdir(wf_dir)):
            if name.endswith((".yml", ".yaml")):
                workflows.append({"file": f".github/workflows/{name}", "name": name})
    return {"workflows": workflows, "read_only": True}


def inspect_prs(*, limit: int = 10) -> dict[str, Any]:
    """Read-only PR inspection via gh CLI when available, else git log proxy."""
    try:
        proc = subprocess.run(
            ["gh", "pr", "list", "--limit", str(limit), "--json", "number,title,state,headRefName,author"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            import json

            return {"pull_requests": json.loads(proc.stdout), "source": "gh_cli", "read_only": True}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {
        "pull_requests": [],
        "source": "unavailable",
        "read_only": True,
        "note": "gh CLI not available; PR listing requires read-only GitHub API in Phase 5",
    }


def github_readonly_summary() -> dict[str, Any]:
    return {
        "branches": inspect_branches(),
        "recent_commits": inspect_recent_commits(),
        "workflows": inspect_workflows(),
        "pull_requests": inspect_prs(),
        "write_access": False,
        "pr_creation": False,
        "merge": False,
    }
