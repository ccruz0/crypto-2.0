"""Controlled auto-execution for staged marketing proposals (additive; manual approval remains)."""

from __future__ import annotations

import logging
from typing import Any

from app.jarvis.approval_storage import get_default_approval_storage
from app.jarvis.marketing_adapter import safe_execute_marketing_proposal

logger = logging.getLogger(__name__)


def should_auto_execute(proposal: dict) -> bool:
    """
    High-confidence or explicitly low-risk action types may run without manual approval.
    """
    if not isinstance(proposal, dict):
        return False
    conf = proposal.get("confidence")
    if conf is not None:
        try:
            if float(conf) > 0.9:
                return True
        except (TypeError, ValueError):
            pass
    at = (proposal.get("action_type") or "").strip()
    if at == "update_budget":
        return True
    return False


def process_staged_action(record: dict) -> dict[str, Any]:
    """
    After staging, optionally auto-execute when ``should_auto_execute`` passes.
    Never raises; failures return ``{"status": "error", "reason": ...}``.
    """
    proposal_index: Any = None
    action_type = ""
    try:
        if not isinstance(record, dict):
            return {"status": "error", "reason": "invalid_record", "proposal_index": None, "action_type": ""}

        args = record.get("args") if isinstance(record.get("args"), dict) else {}
        proposal = args.get("proposal")
        proposal_index = args.get("proposal_index")
        jarvis_run_id = str(record.get("jarvis_run_id") or "").strip()

        if not isinstance(proposal, dict):
            logger.info(
                "jarvis.auto_execution.skipped proposal_index=%s action_type=%s",
                proposal_index,
                "",
            )
            return {
                "status": "skipped",
                "auto_executed": False,
                "reason": "no_proposal",
                "proposal_index": proposal_index,
                "action_type": "",
            }

        action_type = str(proposal.get("action_type") or "")

        if not should_auto_execute(proposal):
            logger.info(
                "jarvis.auto_execution.skipped proposal_index=%s action_type=%s",
                proposal_index,
                action_type,
            )
            return {
                "status": "skipped",
                "auto_executed": False,
                "reason": "rules_not_met",
                "proposal_index": proposal_index,
                "action_type": action_type,
            }

        logger.info(
            "jarvis.auto_execution.triggered proposal_index=%s action_type=%s",
            proposal_index,
            action_type,
        )

        result = safe_execute_marketing_proposal(proposal)
        if isinstance(result, dict) and result.get("status") == "error":
            return {
                "status": "error",
                "reason": str(result.get("error") or "execution_failed"),
                "proposal_index": proposal_index,
                "action_type": action_type,
            }

        store = get_default_approval_storage()
        updated, err = store.finalize_auto_execution_success(
            jarvis_run_id,
            execution_result=result,
        )
        if err:
            return {
                "status": "error",
                "reason": err,
                "proposal_index": proposal_index,
                "action_type": action_type,
            }

        return {
            "status": "ok",
            "auto_executed": True,
            "execution_result": result,
            "record": updated,
            "proposal_index": proposal_index,
            "action_type": action_type,
        }
    except Exception as e:
        logger.exception(
            "jarvis.auto_execution.process_failed proposal_index=%s action_type=%s err=%s",
            proposal_index,
            action_type,
            e,
        )
        return {
            "status": "error",
            "reason": str(e)[:500],
            "proposal_index": proposal_index,
            "action_type": action_type,
        }
