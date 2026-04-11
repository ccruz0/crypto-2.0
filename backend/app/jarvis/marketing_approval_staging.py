"""Stage selected marketing proposals into the existing Jarvis approval store."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.jarvis.approval_storage import build_pending_approval_record, get_default_approval_storage
from app.jarvis.auto_execution import process_staged_action
from app.jarvis.marketing_action_proposals import run_propose_marketing_actions

logger = logging.getLogger(__name__)

_MARKETING_EXEC_TOOL = "execute_marketing_proposal"
_PLACEHOLDER_POLICY = "approval_required"
_PLACEHOLDER_CATEGORY = "write"
_ALL_JARVIS_ENVS = ["dev", "lab", "prod"]


def _priority_to_risk_level(priority: str) -> str:
    p = (priority or "").strip().lower()
    if p == "high":
        return "high"
    if p == "medium":
        return "medium"
    return "low"


def _normalize_indices(
    *,
    action_index: int | None,
    action_indices: list[int] | None,
) -> tuple[list[int], str | None]:
    if action_index is not None:
        if action_index < 0:
            return [], "action_index must be >= 0."
        return [action_index], None

    raw = list(action_indices or [])
    if not raw:
        return [], "action_indices must not be empty."
    if any(x < 0 for x in raw):
        return [], "action_indices must contain only non-negative integers."
    if len(set(raw)) != len(raw):
        return [], "action_indices must not contain duplicates."
    return raw, None


def _selection_error_result(
    *,
    business: str,
    days_back: int,
    top_n: int,
    analysis_status: str,
    proposal_status: str,
    message: str,
    unavailable_sources: list[dict[str, Any]],
    missing_data: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "invalid_selection",
        "business": business,
        "days_back": days_back,
        "top_n": top_n,
        "selected_count": 0,
        "staged_actions": [],
        "skipped_actions": [],
        "analysis_status": analysis_status,
        "proposal_status": proposal_status,
        "unavailable_sources": unavailable_sources,
        "missing_data": missing_data,
        "message": message,
    }


def run_stage_marketing_action_for_approval(
    *,
    days_back: int,
    top_n: int,
    action_index: int | None,
    action_indices: list[int] | None,
    reason: str = "",
) -> dict[str, Any]:
    proposal_result = run_propose_marketing_actions(days_back=days_back, top_n=top_n)
    business = str(proposal_result.get("business") or "Peluquería Cruz")
    proposal_status = str(proposal_result.get("status") or "insufficient_data")
    analysis_status = str(proposal_result.get("analysis_status") or "insufficient_data")
    unavailable_sources = list(proposal_result.get("unavailable_sources") or [])
    missing_data = list(proposal_result.get("missing_data") or [])
    proposals = list(proposal_result.get("proposed_actions") or [])

    if proposal_status == "insufficient_data":
        return {
            "status": "insufficient_data",
            "business": business,
            "days_back": days_back,
            "top_n": top_n,
            "selected_count": 0,
            "staged_actions": [],
            "skipped_actions": [],
            "analysis_status": analysis_status,
            "proposal_status": proposal_status,
            "unavailable_sources": unavailable_sources,
            "missing_data": missing_data,
            "message": "No usable marketing proposals were available to stage.",
        }

    selected_indices, err = _normalize_indices(
        action_index=action_index,
        action_indices=action_indices,
    )
    if err:
        return _selection_error_result(
            business=business,
            days_back=days_back,
            top_n=top_n,
            analysis_status=analysis_status,
            proposal_status=proposal_status,
            message=err,
            unavailable_sources=unavailable_sources,
            missing_data=missing_data,
        )

    max_idx = len(proposals) - 1
    bad = [i for i in selected_indices if i > max_idx]
    if bad:
        return _selection_error_result(
            business=business,
            days_back=days_back,
            top_n=top_n,
            analysis_status=analysis_status,
            proposal_status=proposal_status,
            message=f"Selected action index out of range. Valid range is 0..{max_idx}.",
            unavailable_sources=unavailable_sources,
            missing_data=missing_data,
        )

    store = get_default_approval_storage()
    staging_batch_id = str(uuid.uuid4())
    staging_reason = (reason or "").strip() or None
    staged_actions: list[dict[str, Any]] = []

    for idx in selected_indices:
        proposal = dict(proposals[idx])
        run_id = f"{staging_batch_id}:{idx}"
        title = str(proposal.get("title") or "Untitled marketing action")
        priority = str(proposal.get("priority") or "medium")
        source = str(proposal.get("source") or "marketing")
        record = build_pending_approval_record(
            jarvis_run_id=run_id,
            tool=_MARKETING_EXEC_TOOL,
            args={
                "proposal_index": idx,
                "proposal": proposal,
                "business": business,
                "days_back": days_back,
                "top_n": top_n,
                "staging_reason": staging_reason,
                "staging_batch_id": staging_batch_id,
            },
            policy=_PLACEHOLDER_POLICY,
            category=_PLACEHOLDER_CATEGORY,
            message=f"Marketing action staged for approval: {title}",
            risk_level=_priority_to_risk_level(priority),
            allowed_envs=list(_ALL_JARVIS_ENVS),
            extra_fields={
                "staging_batch_id": staging_batch_id,
                "staged_action_id": run_id,
            },
        )
        store.record_pending(record)
        stored = store.get_by_run_id(run_id) or record
        ae_result = process_staged_action(stored)
        logger.info(
            "jarvis.marketing.staged_for_approval jarvis_run_id=%s tool=%s batch_id=%s index=%s",
            run_id,
            _MARKETING_EXEC_TOOL,
            staging_batch_id,
            idx,
        )
        entry: dict[str, Any] = {
            "jarvis_run_id": run_id,
            "title": title,
            "priority": priority,
            "approval_state": "pending",
            "execution_state": "not_executed",
            "source": source,
            "auto_execution": ae_result,
        }
        if ae_result.get("status") == "ok" and ae_result.get("auto_executed"):
            entry["approval_state"] = "auto_approved"
            entry["execution_state"] = "executed"
        staged_actions.append(entry)

    return {
        "status": "ok",
        "business": business,
        "days_back": days_back,
        "top_n": top_n,
        "selected_count": len(staged_actions),
        "staged_actions": staged_actions,
        "skipped_actions": [],
        "analysis_status": analysis_status,
        "proposal_status": proposal_status,
        "unavailable_sources": unavailable_sources,
        "missing_data": missing_data,
        "staging_batch_id": staging_batch_id,
    }
