"""Jarvis Marketing Intelligence tool entrypoints (read-only, no side effects)."""

from __future__ import annotations

import logging
from typing import Any

from app.jarvis.marketing_approval_staging import (
    run_stage_marketing_action_for_approval,
    run_stage_marketing_action_for_approval_with_proposal_result,
)
from app.jarvis.marketing_action_proposals import build_proposals_from_analysis, run_propose_marketing_actions
from app.jarvis.marketing_adapter import safe_execute_marketing_proposal
from app.jarvis.marketing_schemas import (
    AnalyzeMarketingOpportunitiesArgs,
    ExecuteMarketingProposalArgs,
    MarketingAnalysisWindowArgs,
    ProposeMarketingActionsArgs,
    RunMarketingReviewArgs,
    StageMarketingActionForApprovalArgs,
    TopPagesByConversionArgs,
)
from app.jarvis.marketing_opportunity_analysis import run_analyze_marketing_opportunities
from app.jarvis.marketing_sources import (
    fetch_ga4_booking_funnel,
    fetch_google_ads_summary,
    fetch_search_console_summary,
    fetch_top_pages_by_conversion,
    list_marketing_source_statuses,
)

logger = logging.getLogger(__name__)


def _safe_call(name: str, fn: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        out = fn(**kwargs)
        if not isinstance(out, dict):
            return {
                "status": "unavailable",
                "tool": name,
                "reason": "invalid_tool_result",
                "message": "Marketing tool returned a non-object result.",
            }
        return out
    except Exception as e:
        logger.exception("jarvis.marketing.tool_failed tool=%s err=%s", name, e)
        return {
            "status": "unavailable",
            "tool": name,
            "reason": "internal_error",
            "message": "Marketing tool failed unexpectedly (read-only; no external mutation attempted).",
            "detail": str(e)[:500],
        }


def list_marketing_tools_status(**kwargs: Any) -> dict[str, Any]:
    from app.jarvis.tools import EmptyArgs

    _ = EmptyArgs.model_validate(kwargs)
    try:
        return {
            "status": "ok",
            "business": "Peluquería Cruz",
            "sources": list_marketing_source_statuses(),
        }
    except Exception as e:
        logger.exception("jarvis.marketing.tool_failed tool=list_marketing_tools_status err=%s", e)
        return {
            "status": "unavailable",
            "tool": "list_marketing_tools_status",
            "reason": "internal_error",
            "message": "Could not load marketing source status (read-only).",
            "detail": str(e)[:500],
        }


def get_search_console_summary(**kwargs: Any) -> dict[str, Any]:
    args = MarketingAnalysisWindowArgs.model_validate(kwargs)
    return _safe_call(
        "get_search_console_summary",
        fetch_search_console_summary,
        days_back=args.days_back,
    )


def get_ga4_booking_funnel(**kwargs: Any) -> dict[str, Any]:
    args = MarketingAnalysisWindowArgs.model_validate(kwargs)
    return _safe_call(
        "get_ga4_booking_funnel",
        fetch_ga4_booking_funnel,
        days_back=args.days_back,
    )


def get_google_ads_summary(**kwargs: Any) -> dict[str, Any]:
    args = MarketingAnalysisWindowArgs.model_validate(kwargs)
    return _safe_call(
        "get_google_ads_summary",
        fetch_google_ads_summary,
        days_back=args.days_back,
    )


def get_top_pages_by_conversion(**kwargs: Any) -> dict[str, Any]:
    args = TopPagesByConversionArgs.model_validate(kwargs)
    return _safe_call(
        "get_top_pages_by_conversion",
        fetch_top_pages_by_conversion,
        days_back=args.days_back,
        limit=args.limit,
    )


def analyze_marketing_opportunities(**kwargs: Any) -> dict[str, Any]:
    args = AnalyzeMarketingOpportunitiesArgs.model_validate(kwargs)
    try:
        out = run_analyze_marketing_opportunities(days_back=args.days_back, top_n=args.top_n)
        if not isinstance(out, dict):
            return {
                "status": "unavailable",
                "tool": "analyze_marketing_opportunities",
                "reason": "invalid_result",
                "message": "Analysis returned a non-object result.",
            }
        return out
    except Exception as e:
        logger.exception("jarvis.marketing.tool_failed tool=analyze_marketing_opportunities err=%s", e)
        return {
            "status": "unavailable",
            "tool": "analyze_marketing_opportunities",
            "reason": "internal_error",
            "message": "Opportunity analysis failed unexpectedly (read-only).",
            "detail": str(e)[:500],
        }


def propose_marketing_actions(**kwargs: Any) -> dict[str, Any]:
    args = ProposeMarketingActionsArgs.model_validate(kwargs)
    try:
        out = run_propose_marketing_actions(days_back=args.days_back, top_n=args.top_n)
        if not isinstance(out, dict):
            return {
                "status": "unavailable",
                "tool": "propose_marketing_actions",
                "reason": "invalid_result",
                "message": "Proposal layer returned a non-object result.",
            }
        return out
    except Exception as e:
        logger.exception("jarvis.marketing.tool_failed tool=propose_marketing_actions err=%s", e)
        return {
            "status": "unavailable",
            "tool": "propose_marketing_actions",
            "reason": "internal_error",
            "message": "Marketing action proposals failed unexpectedly (read-only).",
            "detail": str(e)[:500],
        }


_FIND_PRIO = {"high": 0, "medium": 1, "low": 2}


def _top_findings_for_review(analysis: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for x in analysis.get("biggest_opportunities") or []:
        if isinstance(x, dict):
            rows.append({**x, "finding_kind": "opportunity"})
    for x in analysis.get("biggest_wastes") or []:
        if isinstance(x, dict):
            rows.append({**x, "finding_kind": "waste"})
    for x in analysis.get("conversion_gaps") or []:
        if isinstance(x, dict):
            rows.append({**x, "finding_kind": "gap"})

    def _key(d: dict[str, Any]) -> tuple[int, str]:
        pr = str(d.get("priority") or "medium").lower()
        return (_FIND_PRIO.get(pr, 1), str(d.get("title") or ""))

    rows.sort(key=_key)
    return rows[:limit]


def _pipeline_overall_status(
    *,
    invalid_selection: bool,
    proposal_status: str,
    analysis_status: str,
) -> str:
    if invalid_selection:
        return "invalid_selection"
    if proposal_status == "insufficient_data":
        return "insufficient_data"
    if analysis_status == "partial":
        return "partial"
    return "ok"


def _deterministic_review_summary(
    *,
    status: str,
    analysis_status: str,
    proposal_status: str,
    n_findings: int,
    n_proposed: int,
    n_staged: int,
    staged_for_approval: bool,
    unavailable_n: int,
    invalid_detail: str | None,
) -> str:
    if status == "invalid_selection" and invalid_detail:
        return f"Marketing review incomplete: {invalid_detail}"
    parts_a: list[str] = []
    if analysis_status == "insufficient_data" and proposal_status == "insufficient_data":
        parts_a.append("Marketing review completed with limited data.")
    elif unavailable_n > 0:
        parts_a.append(
            f"Marketing review completed with limited data. {unavailable_n} source(s) unavailable.",
        )
    else:
        parts_a.append("Marketing review completed.")
    core = (
        f" {n_findings} top finding(s) highlighted, {n_proposed} action(s) proposed"
    )
    if staged_for_approval and n_staged > 0:
        core += f", {n_staged} action(s) staged for approval."
    elif staged_for_approval and n_staged == 0:
        core += "; staging produced no records."
    else:
        core += "."
    return (parts_a[0] + core).strip()


def run_marketing_review(**kwargs: Any) -> dict[str, Any]:
    """
    Orchestrate analyze → propose → optional staging in one call (no Bedrock; single analysis fetch).
    """
    args = RunMarketingReviewArgs.model_validate(kwargs)
    days_back = args.days_back
    top_n = args.top_n
    reason_str = (args.reason or "").strip() or ""

    try:
        analysis = run_analyze_marketing_opportunities(days_back=days_back, top_n=top_n)
        if not isinstance(analysis, dict):
            return {
                "status": "unavailable",
                "tool": "run_marketing_review",
                "reason": "invalid_analysis",
                "message": "Opportunity analysis returned a non-object result.",
                "summary": "Marketing review failed: invalid analysis payload.",
            }
    except Exception as e:
        logger.exception("jarvis.run_marketing_review analysis err=%s", e)
        return {
            "status": "unavailable",
            "tool": "run_marketing_review",
            "reason": "internal_error",
            "message": "Marketing review failed during analysis.",
            "detail": str(e)[:500],
            "summary": "Marketing review failed during analysis.",
        }

    proposal_result = build_proposals_from_analysis(analysis, days_back=days_back, top_n=top_n)
    business = str(proposal_result.get("business") or "Peluquería Cruz")
    proposal_status = str(proposal_result.get("status") or "insufficient_data")
    analysis_status = str(proposal_result.get("analysis_status") or "insufficient_data")
    unavailable_sources = list(proposal_result.get("unavailable_sources") or [])
    missing_data = list(proposal_result.get("missing_data") or [])
    proposed_actions = list(proposal_result.get("proposed_actions") or [])

    top_findings = _top_findings_for_review(analysis, limit=5)
    proposed_trim = [dict(p) for p in proposed_actions[:5]]

    staged_for_approval_flag = bool(args.stage_for_approval)
    selected_action_count = 0
    staged_actions: list[dict[str, Any]] = []
    invalid_selection = False
    invalid_detail: str | None = None

    if args.stage_for_approval:
        if not proposed_actions:
            selected_action_count = 0
            staged_actions = []
        else:
            raw_indices = args.stage_indices
            if raw_indices is not None and len(raw_indices) > 0:
                indices = sorted(set(raw_indices))
                if len(indices) != len(raw_indices):
                    invalid_selection = True
                    invalid_detail = "Duplicate indices are not allowed."
                else:
                    max_idx = len(proposed_actions) - 1
                    bad = [i for i in indices if i < 0 or i > max_idx]
                    if bad:
                        invalid_selection = True
                        invalid_detail = (
                            f"Invalid action index(es): {bad}. Valid range is 0..{max_idx}."
                        )
                    else:
                        stage_out = run_stage_marketing_action_for_approval_with_proposal_result(
                            proposal_result,
                            days_back=days_back,
                            top_n=top_n,
                            action_index=None,
                            action_indices=indices,
                            reason=reason_str,
                        )
                        selected_action_count = int(stage_out.get("selected_count") or 0)
                        staged_actions = list(stage_out.get("staged_actions") or [])
            else:
                stage_out = run_stage_marketing_action_for_approval_with_proposal_result(
                    proposal_result,
                    days_back=days_back,
                    top_n=top_n,
                    action_index=0,
                    action_indices=None,
                    reason=reason_str,
                )
                selected_action_count = int(stage_out.get("selected_count") or 0)
                staged_actions = list(stage_out.get("staged_actions") or [])

    overall = _pipeline_overall_status(
        invalid_selection=invalid_selection,
        proposal_status=proposal_status,
        analysis_status=analysis_status,
    )
    summary = _deterministic_review_summary(
        status=overall,
        analysis_status=analysis_status,
        proposal_status=proposal_status,
        n_findings=len(top_findings),
        n_proposed=len(proposed_actions),
        n_staged=selected_action_count,
        staged_for_approval=staged_for_approval_flag,
        unavailable_n=len(unavailable_sources),
        invalid_detail=invalid_detail,
    )

    return {
        "status": overall,
        "business": business,
        "days_back": days_back,
        "top_n": top_n,
        "analysis_status": analysis_status,
        "proposal_status": proposal_status,
        "staged_for_approval": staged_for_approval_flag and not invalid_selection,
        "selected_action_count": selected_action_count,
        "top_findings": top_findings,
        "proposed_actions": proposed_trim,
        "staged_actions": staged_actions[:5],
        "missing_data": missing_data,
        "unavailable_sources": unavailable_sources,
        "summary": summary,
    }


def stage_marketing_action_for_approval(**kwargs: Any) -> dict[str, Any]:
    args = StageMarketingActionForApprovalArgs.model_validate(kwargs)
    try:
        out = run_stage_marketing_action_for_approval(
            days_back=args.days_back,
            top_n=args.top_n,
            action_index=args.action_index,
            action_indices=args.action_indices,
            reason=args.reason,
        )
        if not isinstance(out, dict):
            return {
                "status": "unavailable",
                "tool": "stage_marketing_action_for_approval",
                "reason": "invalid_result",
                "message": "Marketing staging returned a non-object result.",
            }
        return out
    except Exception as e:
        logger.exception("jarvis.marketing.tool_failed tool=stage_marketing_action_for_approval err=%s", e)
        return {
            "status": "unavailable",
            "tool": "stage_marketing_action_for_approval",
            "reason": "internal_error",
            "message": "Marketing action staging failed unexpectedly (internal approvals only).",
            "detail": str(e)[:500],
        }


def execute_marketing_proposal(**kwargs: Any) -> dict[str, Any]:
    """Registered tool entrypoint; delegates to :func:`safe_execute_marketing_proposal`."""
    args = ExecuteMarketingProposalArgs.model_validate(kwargs)
    return safe_execute_marketing_proposal(dict(args.proposal))
