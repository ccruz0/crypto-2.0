"""GitHub PR creation service for Jarvis Phase 5 (write disabled by default)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from app.jarvis.change_execution.config import (
    jarvis_github_write_enabled,
    jarvis_pr_creation_enabled,
    jarvis_promote_pr_enabled,
)
from app.jarvis.change_execution.sandbox import block_push_to_main
from app.jarvis.execution.safety import SafetyLevel, classify_phase5_action, is_forbidden
from app.services._paths import workspace_root

logger = logging.getLogger(__name__)

FORBIDDEN_ACTIONS = frozenset({"merge", "close_pr", "deploy", "push_to_main", "force_push", "delete_branch"})


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 60) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def check_pr_creation_allowed(
    *,
    tests_passed: bool,
    patch_safety_passed: bool,
    gate2_approved: bool,
) -> dict[str, Any]:
    """Verify all prerequisites for Phase-5 Gate 2 PR creation."""
    reasons: list[str] = []
    if not jarvis_pr_creation_enabled():
        reasons.append("JARVIS_PR_CREATION_ENABLED=false")
    if not jarvis_github_write_enabled():
        reasons.append("JARVIS_GITHUB_WRITE_ENABLED=false")
    if not gate2_approved:
        reasons.append("Gate 2 approval not recorded")
    if not tests_passed:
        reasons.append("Tests did not pass")
    if not patch_safety_passed:
        reasons.append("Patch safety check failed")
    if is_forbidden(classify_phase5_action("merge")):
        pass  # merge always forbidden — no action needed
    return {
        "allowed": len(reasons) == 0,
        "reasons": reasons,
        "flags": {
            "pr_creation_enabled": jarvis_pr_creation_enabled(),
            "github_write_enabled": jarvis_github_write_enabled(),
        },
    }


def check_lab_promote_pr_allowed(
    *,
    lab_passed: bool,
    tests_passed: bool,
    patch_safety_passed: bool,
    stub_patch: bool,
    already_promoted: bool,
) -> dict[str, Any]:
    """Prerequisites for Promote-from-LAB (scoped; independent of Gate-2 flags)."""
    reasons: list[str] = []
    if not jarvis_promote_pr_enabled():
        reasons.append("JARVIS_PROMOTE_PR_ENABLED=false")
    if already_promoted:
        reasons.append("Already promoted (PR already opened for this trial)")
    if stub_patch:
        reasons.append("Stub/TODO patches cannot be promoted")
    if not lab_passed:
        reasons.append("LAB trial has not passed")
    if not tests_passed:
        reasons.append("LAB tests did not pass")
    if not patch_safety_passed:
        reasons.append("Patch safety check failed")
    return {
        "allowed": len(reasons) == 0,
        "reasons": reasons,
        "flags": {
            "promote_pr_enabled": jarvis_promote_pr_enabled(),
            # Intentionally do NOT require broad github_write / pr_creation.
            "pr_creation_enabled": jarvis_pr_creation_enabled(),
            "github_write_enabled": jarvis_github_write_enabled(),
        },
    }


def prepare_sandbox_branch_for_push(
    *,
    workdir: Path,
    branch_name: str,
    commit_message: str,
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    """Commit sandbox changes and retarget origin to the workspace GitHub remote.

    Sandbox clones use a local-path origin; GitHub push needs the real remote URL.
    Never pushes to main/master.

    When ``changed_files`` is provided (LAB promote path), only those paths are
    staged — never ``git add -A``, which would include sandbox artifacts such as
    ``approved.patch`` / ``test_results.json``.
    """
    if block_push_to_main(branch_name):
        return {"ok": False, "error": "push to main/master is forbidden"}

    root = workspace_root()
    code, remote_url, err = _run(["git", "remote", "get-url", "origin"], cwd=root, timeout=30)
    if code != 0 or not (remote_url or "").strip():
        return {"ok": False, "error": f"could not resolve GitHub remote from workspace: {err or remote_url}"}

    code, _, err = _run(["git", "remote", "set-url", "origin", remote_url.strip()], cwd=workdir, timeout=30)
    if code != 0:
        # Remote may not exist yet in some fallback sandboxes.
        _run(["git", "remote", "remove", "origin"], cwd=workdir, timeout=15)
        code, _, err = _run(
            ["git", "remote", "add", "origin", remote_url.strip()],
            cwd=workdir,
            timeout=30,
        )
        if code != 0:
            return {"ok": False, "error": f"failed to set origin remote: {err}"}

    code, _, err = _run(["git", "checkout", "-B", branch_name], cwd=workdir, timeout=30)
    if code != 0:
        return {"ok": False, "error": f"checkout branch failed: {err}"}

    if changed_files:
        for rel in changed_files:
            rel_n = str(rel or "").strip().lstrip("./")
            if not rel_n or rel_n.startswith("/") or ".." in Path(rel_n).parts:
                return {"ok": False, "error": f"invalid changed file path: {rel}"}
            code, _, err = _run(["git", "add", "--", rel_n], cwd=workdir, timeout=60)
            if code != 0:
                return {"ok": False, "error": f"git add failed for {rel_n}: {err}"}
    else:
        # Legacy callers: stage tracked modifications only (not untracked sandbox junk).
        code, _, err = _run(["git", "add", "-u"], cwd=workdir, timeout=60)
        if code != 0:
            return {"ok": False, "error": f"git add failed: {err}"}

    # Commit only when there is something to commit.
    code, status_out, _ = _run(["git", "status", "--porcelain"], cwd=workdir, timeout=30)
    if code == 0 and status_out.strip():
        code, _, err = _run(
            ["git", "commit", "-m", commit_message],
            cwd=workdir,
            timeout=60,
        )
        if code != 0:
            return {"ok": False, "error": f"git commit failed: {err}"}

    return {"ok": True, "remote_url_host": remote_url.strip().split("@")[-1][:80]}


def build_pr_body(
    *,
    task_id: str,
    objective: str,
    changed_files: list[str],
    test_results: dict[str, Any],
    review: dict[str, Any],
    safety_report: dict[str, Any],
    artifact_links: list[str] | None = None,
) -> str:
    """Build PR description with safety report (no secrets)."""
    lines = [
        "## Jarvis Phase 5 Change Request",
        "",
        f"**Task ID:** `{task_id}`",
        f"**Objective:** {objective}",
        "",
        "### Changed Files",
    ]
    for f in changed_files[:50]:
        lines.append(f"- `{f}`")
    if len(changed_files) > 50:
        lines.append(f"- ... and {len(changed_files) - 50} more")

    lines.extend(
        [
            "",
            "### Test Results",
            f"- Backend passed: {test_results.get('backend_tests', {}).get('passed', test_results.get('passed'))}",
            f"- Frontend build: {test_results.get('frontend_build', {})}",
            "",
            "### Review",
            f"- Risk score: {review.get('risk_score', 'N/A')}",
            f"- Recommendation: {review.get('approval_recommendation', 'N/A')}",
            "",
            "### Safety Report",
            f"- Patch safety passed: {safety_report.get('passed', False)}",
            f"- Forbidden paths blocked: {safety_report.get('blocked_paths', [])}",
            f"- PR creation flags: {safety_report.get('flags', {})}",
            "",
            "### Artifacts",
        ]
    )
    for link in artifact_links or []:
        lines.append(f"- {link}")

    lines.extend(
        [
            "",
            "---",
            "*Created by Jarvis Phase 5. Auto-merge and deploy are disabled.*",
        ]
    )
    return "\n".join(lines)


def create_pull_request(
    *,
    task_id: str,
    branch_name: str,
    title: str,
    body: str,
    workdir: Path,
    labels: list[str] | None = None,
    mock: bool = False,
    via_lab_promote: bool = False,
) -> dict[str, Any]:
    """
    Push branch and create PR. Never merges or deploys.
    Returns mock PR in test mode or when JARVIS_PR_MOCK=1.

    via_lab_promote=True uses JARVIS_PROMOTE_PR_ENABLED only (does not require
    broad JARVIS_PR_CREATION_ENABLED / JARVIS_GITHUB_WRITE_ENABLED).
    """
    result: dict[str, Any] = {
        "task_id": task_id,
        "branch_name": branch_name,
        "title": title,
        "success": False,
        "mock": mock,
        "merge": False,
        "deploy": False,
        "via_lab_promote": via_lab_promote,
    }

    action_level = classify_phase5_action("pr_creation")
    if is_forbidden(action_level):
        result["error"] = "pr_creation forbidden"
        return result

    if block_push_to_main(branch_name):
        result["error"] = "push to main/master is forbidden"
        return result

    if mock or os.environ.get("JARVIS_PR_MOCK") == "1":
        result.update(
            {
                "success": True,
                "pr_url": f"https://github.com/example/repo/pull/mock-{task_id[:8]}",
                "pr_number": 0,
                "mock": True,
                "note": "Mock PR — no remote write performed",
            }
        )
        return result

    if via_lab_promote:
        if not jarvis_promote_pr_enabled():
            result["error"] = "JARVIS_PROMOTE_PR_ENABLED=false"
            return result
    else:
        prereq = check_pr_creation_allowed(
            tests_passed=True, patch_safety_passed=True, gate2_approved=True
        )
        if not prereq["allowed"]:
            result["error"] = "; ".join(prereq["reasons"])
            result["prerequisites"] = prereq
            return result

        if not jarvis_github_write_enabled() or not jarvis_pr_creation_enabled():
            result["error"] = "GitHub write/PR creation disabled"
            return result

    # Push branch (never to main)
    code, out, err = _run(["git", "push", "-u", "origin", branch_name], cwd=workdir, timeout=120)
    if code != 0:
        result["error"] = f"push failed: {err or out}"
        return result

    # Create PR via gh CLI
    default_labels = ["jarvis", "lab-promote"] if via_lab_promote else ["jarvis", "automated"]
    gh_args = [
        "gh",
        "pr",
        "create",
        "--head",
        branch_name,
        "--title",
        title,
        "--body",
        body,
        "--base",
        "main",
    ]
    for label in labels or default_labels:
        gh_args.extend(["--label", label])

    code, out, err = _run(gh_args, cwd=workdir, timeout=60)
    if code != 0:
        result["error"] = f"gh pr create failed: {err or out}"
        return result

    pr_url = out.strip()
    result.update({"success": True, "pr_url": pr_url, "merge": False, "deploy": False})
    return result


def block_forbidden_action(action: str) -> dict[str, Any]:
    """Explicitly block merge/deploy/push-to-main etc."""
    key = (action or "").strip().lower()
    if key in FORBIDDEN_ACTIONS or is_forbidden(classify_phase5_action(key)):
        return {"blocked": True, "action": key, "reason": f"{key} is FORBIDDEN"}
    return {"blocked": False, "action": key}
