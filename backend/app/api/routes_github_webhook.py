"""GitHub Actions webhook endpoint.

Receives ``workflow_run`` events from GitHub, validates the HMAC
signature, and drives the post-deploy lifecycle:

    deploy success  ->  automatic smoke check  ->  task done
    deploy failure  ->  Telegram alert          ->  task stays in deploying

Required env: ``GITHUB_WEBHOOK_SECRET``
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_signature(payload: bytes, signature: str | None) -> bool:
    secret = (os.environ.get("GITHUB_WEBHOOK_SECRET") or "").strip()
    if not secret:
        logger.error("github_webhook: GITHUB_WEBHOOK_SECRET not set — rejecting")
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


_DEPLOY_WORKFLOW_FILE = (
    (os.environ.get("DEPLOY_WORKFLOW_FILE") or "").strip()
    or "deploy_session_manager.yml"
)


def _is_deploy_workflow(workflow_path: str, workflow_name: str) -> bool:
    """True if this workflow run is the deploy workflow we care about."""
    path = (workflow_path or "").lower()
    name = (workflow_name or "").lower()
    target = _DEPLOY_WORKFLOW_FILE.lower()
    return target in path or target.replace(".yml", "") in name


def _resolve_task_id() -> str:
    """Find the task currently in ``deploying`` status.

    First checks the in-process deploy tracker, then falls back to a
    Notion query.
    """
    try:
        from app.services.deploy_trigger import get_last_deploy_task_id
        tid = get_last_deploy_task_id()
        if tid:
            return tid
    except Exception:
        pass

    try:
        from app.services.notion_task_reader import get_tasks_by_status
        tasks = get_tasks_by_status(["deploying", "Deploying"], max_results=1)
        if tasks:
            return str(tasks[0].get("id") or "")
    except Exception as exc:
        logger.warning("github_webhook: Notion lookup for deploying task failed: %s", exc)
    return ""


def _send_telegram_alert(text: str) -> None:
    try:
        from app.services.agent_telegram_approval import (
            _get_default_chat_id,
            _send_telegram_message,
        )
        chat_id = _get_default_chat_id()
        if chat_id:
            _send_telegram_message(chat_id, text)
    except Exception as exc:
        logger.warning("github_webhook: Telegram alert failed: %s", exc)


def _handle_workflow_run(body: dict[str, Any]) -> dict[str, Any]:
    """Process a ``workflow_run`` event payload."""
    run = body.get("workflow_run") or {}
    conclusion = (run.get("conclusion") or "").lower()
    action = (body.get("action") or "").lower()
    workflow_name = run.get("name", "unknown")
    workflow_path = run.get("path", "")
    run_url = run.get("html_url", "")

    logger.info(
        "github_webhook: received workflow_run action=%s workflow=%s path=%s",
        action, workflow_name, workflow_path,
    )

    if action != "completed":
        return {"ok": True, "ignored": True, "reason": f"action={action} (not completed)"}

    if not _is_deploy_workflow(workflow_path, workflow_name):
        logger.info(
            "github_webhook: workflow=%r ignored (not deploy target %s)",
            workflow_name, _DEPLOY_WORKFLOW_FILE,
        )
        return {"ok": True, "ignored": True, "reason": f"workflow '{workflow_name}' not deploy target"}

    task_id = _resolve_task_id()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not task_id:
        logger.info("github_webhook: no matching deploying task, ignoring")
        return {"ok": True, "ignored": True, "reason": "no deploying task found"}

    logger.info(
        "github_webhook: workflow_run completed conclusion=%s task_id=%s workflow=%s",
        conclusion, task_id, workflow_name,
    )

    if conclusion == "success":
        return _handle_deploy_success(task_id, ts, run_url)

    return _handle_deploy_failure(task_id, ts, conclusion, run_url)


def _handle_deploy_success(task_id: str, ts: str, run_url: str) -> dict[str, Any]:
    logger.info("github_webhook: deploy succeeded — running smoke check for task %s", task_id)

    try:
        from app.services.deploy_smoke_check import (
            format_smoke_result_for_telegram,
            run_and_record_smoke_check,
        )
        result = run_and_record_smoke_check(
            task_id,
            advance_on_pass=True,
            current_status="deploying",
        )
        outcome = result.get("outcome", "unknown")
        logger.info(
            "github_webhook: smoke_check outcome=%s task_id=%s advanced=%s",
            outcome, task_id, result.get("advanced"),
        )

        tg_text = format_smoke_result_for_telegram(result)
        if result.get("advanced"):
            tg_text += f"\n\nTask {task_id[:8]}… advanced to <b>done</b>."
        elif result.get("blocked"):
            tg_text += f"\n\nTask {task_id[:8]}… marked <b>blocked</b>."
        _send_telegram_alert(tg_text)

        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("webhook_smoke_check", task_id=task_id, details={
                "outcome": outcome,
                "advanced": result.get("advanced"),
                "run_url": run_url,
            })
        except Exception:
            pass

        return {"handled": True, "task_id": task_id, "smoke_outcome": outcome}

    except Exception as exc:
        logger.error("github_webhook: smoke check failed for task %s: %s", task_id, exc, exc_info=True)
        _send_telegram_alert(
            f"Deploy succeeded but smoke check raised an error for task {task_id[:8]}…\n"
            f"Error: {str(exc)[:300]}"
        )
        return {"handled": False, "task_id": task_id, "error": str(exc)}


def _handle_deploy_failure(
    task_id: str, ts: str, conclusion: str, run_url: str,
) -> dict[str, Any]:
    logger.warning(
        "github_webhook: deploy %s for task %s — sending alert",
        conclusion, task_id,
    )

    try:
        from app.services.notion_tasks import update_notion_task_metadata
        update_notion_task_metadata(
            task_id,
            {"deploy_result": f"{conclusion} at {ts}"},
            append_comment=f"[{ts}] Deploy workflow {conclusion}.\nRun: {run_url}",
        )
    except Exception as exc:
        logger.warning("github_webhook: Notion metadata write failed: %s", exc)

    _send_telegram_alert(
        f"<b>Deploy {conclusion}</b> for task {task_id[:8]}…\n"
        f"Task remains in <b>deploying</b>.\n"
        f"<a href=\"{run_url}\">View workflow run</a>"
    )

    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("deploy_workflow_failed", task_id=task_id, details={
            "conclusion": conclusion,
            "run_url": run_url,
        })
    except Exception:
        pass

    return {"handled": True, "task_id": task_id, "conclusion": conclusion}


@router.post("/github/actions")
async def github_actions_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
) -> dict[str, Any]:
    """Receive GitHub webhook events for workflow runs."""
    payload = await request.body()

    if not _verify_signature(payload, x_hub_signature_256):
        logger.warning("github_webhook: invalid signature — rejecting")
        return Response(status_code=403, content="Invalid signature")  # type: ignore[return-value]

    event = (x_github_event or "").lower()
    if event != "workflow_run":
        return {"ok": True, "event": event, "handled": False}

    import json
    try:
        body = json.loads(payload)
    except Exception as e:
        logger.warning("github_webhook: invalid JSON — %s", e)
        return {"ok": False, "error": "invalid JSON"}

    result = _handle_workflow_run(body)
    return {"ok": True, "event": event, **result}
