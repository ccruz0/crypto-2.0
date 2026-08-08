"""GitHub PR creation service for Jarvis Phase 5 (write disabled by default)."""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app.jarvis.change_execution.config import (
    jarvis_github_write_enabled,
    jarvis_pr_creation_enabled,
    jarvis_promote_pr_enabled,
)
from app.jarvis.change_execution.sandbox import block_push_to_main
from app.jarvis.execution.safety import classify_phase5_action, is_forbidden
from app.services._paths import workspace_root

logger = logging.getLogger(__name__)

FORBIDDEN_ACTIONS = frozenset({"merge", "close_pr", "deploy", "push_to_main", "force_push", "delete_branch"})
_DEFAULT_REPO = "ccruz0/crypto-2.0"
_GITHUB_API = "https://api.github.com"


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def _redact_secrets(text: str) -> str:
    """Strip credential material from command output before returning/logging."""
    out = text or ""
    out = re.sub(r"x-access-token:[^@\s]+@", "x-access-token:***@", out)
    # Generic userinfo, but do not re-mangle already-redacted x-access-token URLs.
    out = re.sub(r"://(?!x-access-token:)[^/\s:@]+:[^@\s]+@", "://***:***@", out)
    out = re.sub(
        r"(?i)(Authorization:\s*(?:bearer|basic))\s+\S+",
        lambda m: f"{m.group(1)} ***",
        out,
    )
    out = re.sub(r"\bgh[pous]_[A-Za-z0-9_]+\b", "[REDACTED]", out)
    out = re.sub(r"\bgithub_pat_[A-Za-z0-9_]+\b", "[REDACTED]", out)
    return out[:800]


def _git_basic_auth_header(token: str) -> str:
    """Build Authorization: Basic … for Git smart-HTTP (x-access-token + installation token)."""
    raw = f"x-access-token:{token}".encode("utf-8")
    return f"Authorization: Basic {base64.b64encode(raw).decode('ascii')}"


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

    if changed_files is not None:
        if not changed_files:
            return {"ok": False, "error": "changed_files is empty; nothing to stage for promote"}
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
    if code != 0:
        return {"ok": False, "error": "git status failed after staging"}
    if not status_out.strip():
        if changed_files is not None:
            return {
                "ok": False,
                "error": "no staged changes after adding changed_files; refusing empty promote commit",
            }
        # Legacy: already committed or clean tree — allow push of existing tip.
        return {"ok": True, "remote_url_host": remote_url.strip().split("@")[-1][:80]}

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


def _resolve_github_repo(workdir: Path) -> str:
    """Return owner/repo for API calls (no credentials)."""
    env_repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if env_repo and "/" in env_repo and " " not in env_repo:
        return env_repo

    for cwd in (workdir, workspace_root()):
        code, remote_url, _ = _run(["git", "remote", "get-url", "origin"], cwd=cwd, timeout=15)
        if code != 0:
            continue
        slug = _repo_slug_from_remote(remote_url.strip())
        if slug:
            return slug
    return _DEFAULT_REPO


def _repo_slug_from_remote(remote_url: str) -> str | None:
    url = (remote_url or "").strip()
    if not url:
        return None
    if url.startswith("git@"):
        # git@github.com:owner/repo.git
        try:
            path = url.split(":", 1)[1]
        except IndexError:
            return None
    else:
        parts = urlsplit(url)
        path = parts.path or ""
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    segments = [s for s in path.split("/") if s]
    if len(segments) >= 2:
        return f"{segments[0]}/{segments[1]}"
    return None


def _authed_https_remote(remote_url: str, token: str) -> str | None:
    """Build https://x-access-token:TOKEN@github.com/owner/repo.git without logging it."""
    url = (remote_url or "").strip()
    if not url or not token:
        return None
    if url.startswith("git@"):
        slug = _repo_slug_from_remote(url)
        if not slug:
            return None
        encoded = quote(token, safe="")
        return f"https://x-access-token:{encoded}@github.com/{slug}.git"
    if url.startswith("https://") and "github.com" in url:
        parts = urlsplit(url)
        # Drop any embedded userinfo before injecting the installation token.
        netloc = parts.hostname or "github.com"
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        encoded = quote(token, safe="")
        authed_netloc = f"x-access-token:{encoded}@{netloc}"
        return urlunsplit((parts.scheme, authed_netloc, parts.path, parts.query, parts.fragment))
    return None


def _push_branch(*, workdir: Path, branch_name: str, token: str) -> dict[str, Any]:
    """Push branch with short-lived Basic auth header (never writes token into origin URL)."""
    code, remote_url, err = _run(["git", "remote", "get-url", "origin"], cwd=workdir, timeout=15)
    if code != 0 or not (remote_url or "").strip():
        return {"ok": False, "error": f"could not read origin remote: {_redact_secrets(err or remote_url)}"}

    slug = _repo_slug_from_remote(remote_url.strip())
    if not slug or not token:
        return {
            "ok": False,
            "error": "unsupported git remote for authenticated push (need github.com HTTPS or SSH URL)",
        }

    # Push to an explicit HTTPS URL so we never mutate origin with credentials.
    # GitHub Git smart-HTTP expects Basic (x-access-token:TOKEN), not Bearer.
    # Token lives only in process argv for the duration of this push (not .git/config).
    push_url = f"https://github.com/{slug}.git"
    auth_header = _git_basic_auth_header(token)
    env = {
        **os.environ,
        "GIT_ASKPASS": "echo",
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
    }
    code, out, err = _run(
        [
            "git",
            "-c",
            f"http.extraHeader={auth_header}",
            "push",
            "-u",
            push_url,
            f"HEAD:refs/heads/{branch_name}",
        ],
        cwd=workdir,
        timeout=120,
        env=env,
    )
    if code != 0:
        return {"ok": False, "error": f"push failed: {_redact_secrets(err or out)}"}
    return {"ok": True}


def _create_pr_via_api(
    *,
    repo: str,
    token: str,
    branch_name: str,
    title: str,
    body: str,
    labels: list[str],
    base: str = "main",
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "title": (title or "")[:256],
        "body": body or "",
        "head": branch_name,
        "base": base,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{_GITHUB_API}/repos/{repo}/pulls", headers=headers, json=payload)
            if resp.status_code not in (200, 201):
                return {
                    "ok": False,
                    "error": f"GitHub PR API HTTP {resp.status_code}: {_redact_secrets(resp.text[:400])}",
                }
            data = resp.json()
            pr_url = (data.get("html_url") or "").strip()
            pr_number = data.get("number")
            if labels and pr_number is not None:
                try:
                    label_resp = client.post(
                        f"{_GITHUB_API}/repos/{repo}/issues/{pr_number}/labels",
                        headers=headers,
                        json={"labels": labels},
                    )
                    if label_resp.status_code not in (200, 201):
                        logger.warning(
                            "PR created but labeling failed HTTP %s (labels best-effort)",
                            label_resp.status_code,
                        )
                except Exception as label_exc:
                    logger.warning("PR created but labeling failed: %s", label_exc)
            return {"ok": True, "pr_url": pr_url, "pr_number": pr_number}
    except Exception as exc:
        return {"ok": False, "error": f"GitHub PR API error: {_redact_secrets(str(exc))}"}


def _create_pr_via_gh_cli(
    *,
    workdir: Path,
    branch_name: str,
    title: str,
    body: str,
    labels: list[str],
    token: str,
) -> dict[str, Any]:
    """Optional fallback when ``gh`` is installed (host tooling); not required in AWS containers."""
    if not shutil.which("gh"):
        return {"ok": False, "error": "gh CLI not available"}

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
    for label in labels:
        gh_args.extend(["--label", label])

    env = {
        **os.environ,
        "GH_TOKEN": token,
        "GITHUB_TOKEN": token,
        "GIT_TERMINAL_PROMPT": "0",
    }
    code, out, err = _run(gh_args, cwd=workdir, timeout=60, env=env)
    if code != 0:
        return {"ok": False, "error": f"gh pr create failed: {_redact_secrets(err or out)}"}
    return {"ok": True, "pr_url": out.strip(), "pr_number": None}


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

    Auth preference (same as cursor bridge / deploy trigger):
    1. GitHub App installation token via get_github_api_token()
    2. Legacy PAT when ALLOW_LEGACY_GITHUB_PAT=true

    Creates the PR via GitHub REST API (preferred). Falls back to ``gh`` only when
    the CLI is present — AWS backend containers do not ship ``gh``.

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

    from app.services.github_app_auth import get_github_api_token

    token, auth_method = get_github_api_token()
    if not token:
        result["error"] = (
            "GitHub auth unavailable: configure GITHUB_APP_* "
            "(or ALLOW_LEGACY_GITHUB_PAT=true with GITHUB_TOKEN)"
        )
        result["auth_method"] = auth_method
        return result

    result["auth_method"] = auth_method
    logger.info(
        "jarvis_pr_create auth_method=%s via_lab_promote=%s task_id=%s",
        auth_method,
        via_lab_promote,
        task_id,
    )

    push = _push_branch(workdir=workdir, branch_name=branch_name, token=token)
    if not push.get("ok"):
        result["error"] = push.get("error") or "push failed"
        return result

    default_labels = ["jarvis", "lab-promote"] if via_lab_promote else ["jarvis", "automated"]
    label_list = list(labels or default_labels)
    repo = _resolve_github_repo(workdir)

    api_result = _create_pr_via_api(
        repo=repo,
        token=token,
        branch_name=branch_name,
        title=title,
        body=body,
        labels=label_list,
    )
    if api_result.get("ok"):
        result.update(
            {
                "success": True,
                "pr_url": api_result.get("pr_url") or "",
                "pr_number": api_result.get("pr_number"),
                "merge": False,
                "deploy": False,
                "transport": "github_api",
            }
        )
        return result

    # Fallback for developer hosts that have gh installed.
    gh_result = _create_pr_via_gh_cli(
        workdir=workdir,
        branch_name=branch_name,
        title=title,
        body=body,
        labels=label_list,
        token=token,
    )
    if gh_result.get("ok"):
        result.update(
            {
                "success": True,
                "pr_url": gh_result.get("pr_url") or "",
                "pr_number": gh_result.get("pr_number"),
                "merge": False,
                "deploy": False,
                "transport": "gh_cli",
            }
        )
        return result

    result["error"] = api_result.get("error") or gh_result.get("error") or "PR creation failed"
    return result


def block_forbidden_action(action: str) -> dict[str, Any]:
    """Explicitly block merge/deploy/push-to-main etc."""
    key = (action or "").strip().lower()
    if key in FORBIDDEN_ACTIONS or is_forbidden(classify_phase5_action(key)):
        return {"blocked": True, "action": key, "reason": f"{key} is FORBIDDEN"}
    return {"blocked": False, "action": key}
