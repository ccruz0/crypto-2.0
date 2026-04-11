"""Jarvis Marketing Intelligence tool entrypoints (read-only, no side effects)."""

from __future__ import annotations

import logging
from typing import Any

from app.jarvis.marketing_approval_staging import run_stage_marketing_action_for_approval
from app.jarvis.marketing_action_proposals import run_propose_marketing_actions
from app.jarvis.marketing_adapter import safe_execute_marketing_proposal
from app.jarvis.marketing_schemas import (
    AnalyzeMarketingOpportunitiesArgs,
    ExecuteMarketingProposalArgs,
    MarketingAnalysisWindowArgs,
    ProposeMarketingActionsArgs,
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
