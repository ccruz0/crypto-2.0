"""Trigger deployment via GitHub Actions workflow_dispatch.

Uses the GitHub Actions API to dispatch the primary deploy workflow
(``deploy_session_manager.yml``) on the ``main`` branch.  This is the
same mechanism used elsewhere in the codebase (see
``routes_monitoring.py`` / ``dashboard_data_integrity`` workflow).

Required environment variables
------------------------------
GITHUB_TOKEN
    GitHub Personal Access Token with ``actions:write`` scope.
GITHUB_REPOSITORY
    Repo in ``owner/repo`` format.  Defaults to ``ccruz0/crypto-2.0``.
DEPLOY_WORKFLOW_FILE
    Workflow filename.  Defaults to ``deploy_session_manager.yml``.

The module is intentionally minimal: one public function, no retries,
no polling for workflow completion.  Smoke checks and status updates
are handled by the caller (Telegram handler) and the existing smoke
check infrastructure.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_DEFAULT_REPO = "ccruz0/crypto-2.0"
_DEFAULT_WORKFLOW = "deploy_session_manager.yml"
_DEFAULT_REF = "main"

# Track recent deploys so the GitHub webhook can correlate workflow runs
# to Notion task IDs without requiring workflow input parameters.
_recent_deploys: list[dict[str, str]] = []
_MAX_RECENT_DEPLOYS = 20


def get_last_deploy_task_id() -> str:
    """Return the task_id of the most recent successful deploy dispatch, or ''."""
    for d in reversed(_recent_deploys):
        if d.get("task_id"):
            return d["task_id"]
    return ""


def _get_config() -> tuple[str, str, str]:
    """Return (token, repo, workflow_file).  Token may be empty."""
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip() or _DEFAULT_REPO
    workflow = (os.environ.get("DEPLOY_WORKFLOW_FILE") or "").strip() or _DEFAULT_WORKFLOW
    return token, repo, workflow


def trigger_deploy_workflow(
    *,
    task_id: str = "",
    triggered_by: str = "",
    ref: str = "",
) -> dict[str, Any]:
    """Trigger the deploy workflow via GitHub Actions ``workflow_dispatch``.

    Parameters
    ----------
    task_id:
        Notion task ID (for logging/traceability only).
    triggered_by:
        Username or identifier of the person who approved.
    ref:
        Git ref to deploy.  Defaults to ``main``.

    Returns
    -------
    dict with keys:
        ok (bool):  True if GitHub accepted the dispatch (HTTP 204).
        summary (str):  Human-readable one-line result.
        status_code (int):  HTTP status from GitHub, or 0 on error.
        repo (str):  The target repository.
        workflow (str):  The workflow file dispatched.
        ref (str):  The git ref used.
        error (str):  Error message if ok is False.
        triggered_at (str):  ISO timestamp.
    """
    token, repo, workflow = _get_config()
    target_ref = (ref or "").strip() or _DEFAULT_REF
    triggered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    base = {
        "ok": False,
        "summary": "",
        "status_code": 0,
        "repo": repo,
        "workflow": workflow,
        "ref": target_ref,
        "error": "",
        "triggered_at": triggered_at,
    }

    if not token:
        msg = (
            "GITHUB_TOKEN is not set — cannot trigger deploy. "
            "Set a GitHub PAT with actions:write scope."
        )
        logger.error("trigger_deploy_workflow: %s task_id=%s", msg, task_id)
        return {**base, "summary": msg, "error": msg}

    url = f"{_GITHUB_API}/repos/{repo}/actions/workflows/{workflow}/dispatches"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {"ref": target_ref}

    logger.info(
        "trigger_deploy_workflow: dispatching repo=%s workflow=%s ref=%s task_id=%s triggered_by=%s",
        repo, workflow, target_ref, task_id, triggered_by,
    )

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload, headers=headers)
    except Exception as exc:
        msg = f"GitHub API request failed: {exc}"
        logger.error("trigger_deploy_workflow: %s task_id=%s", msg, task_id, exc_info=True)
        return {**base, "summary": msg, "error": msg}

    base["status_code"] = resp.status_code

    if resp.status_code == 204:
        summary = f"Deploy workflow dispatched: {repo}@{target_ref} ({workflow})"
        logger.info("trigger_deploy_workflow: success — %s task_id=%s", summary, task_id)
        _recent_deploys.append({
            "task_id": task_id,
            "triggered_at": triggered_at,
            "triggered_by": triggered_by,
        })
        if len(_recent_deploys) > _MAX_RECENT_DEPLOYS:
            _recent_deploys[:] = _recent_deploys[-_MAX_RECENT_DEPLOYS:]
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "deploy_workflow_triggered",
                task_id=task_id or None,
                details={
                    "repo": repo,
                    "workflow": workflow,
                    "ref": target_ref,
                    "triggered_by": triggered_by,
                },
            )
        except Exception:
            pass
        return {**base, "ok": True, "summary": summary}

    # Non-204 response
    body = ""
    try:
        body = resp.text[:500]
    except Exception:
        pass
    msg = f"GitHub API returned HTTP {resp.status_code}: {body}"
    logger.error("trigger_deploy_workflow: %s task_id=%s", msg, task_id)
    return {**base, "summary": msg, "error": msg}
