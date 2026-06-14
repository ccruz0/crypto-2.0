"""Jarvis Phase 4C metrics service — read-only analytics orchestration."""

from __future__ import annotations

from typing import Any

from app.jarvis.analytics.aggregation import (
    _QUALITY_PENALTIES,
    _TOOL_ERROR_PENALTY,
    aggregate_investigation_metrics,
    aggregate_proposal_metrics,
    aggregate_root_cause_metrics,
    aggregate_template_metrics,
    aggregate_tool_metrics,
    compute_quality_score,
    count_tool_errors,
    fetch_all_investigations,
    fetch_execution_logs,
    fetch_proposal_tasks,
    filter_rows_since,
)
from app.jarvis.analytics.trend_analysis import (
    build_daily_investigation_trends,
    build_quality_score_trends,
    compute_period_rates,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus


def _quality_block(
    investigations: list[dict[str, Any]],
    logs: list[dict[str, Any]],
) -> dict[str, Any]:
    tool_errors = count_tool_errors(logs, investigations)
    overall = compute_quality_score(investigations, tool_errors=tool_errors)
    last_7 = filter_rows_since(investigations, 7)
    last_30 = filter_rows_since(investigations, 30)
    logs_7 = filter_rows_since(logs, 7)
    logs_30 = filter_rows_since(logs, 30)
    return {
        "overall_score": overall,
        "last_7_days": compute_quality_score(last_7, tool_errors=count_tool_errors(logs_7, last_7)),
        "last_30_days": compute_quality_score(last_30, tool_errors=count_tool_errors(logs_30, last_30)),
        "formula": {
            "base": 100,
            "partial_failure_penalty": _QUALITY_PENALTIES[InvestigationStatus.PARTIAL_FAILURE.value],
            "failed_penalty": _QUALITY_PENALTIES[InvestigationStatus.FAILED.value],
            "insufficient_evidence_penalty": _QUALITY_PENALTIES[InvestigationStatus.INSUFFICIENT_EVIDENCE.value],
            "tool_error_penalty": _TOOL_ERROR_PENALTY,
        },
    }


def get_overview_analytics() -> dict[str, Any]:
    investigations = fetch_all_investigations()
    logs = fetch_execution_logs()
    metrics = aggregate_investigation_metrics(investigations)
    last_7 = filter_rows_since(investigations, 7)
    last_30 = filter_rows_since(investigations, 30)
    trends_7 = build_daily_investigation_trends(investigations, days=7)
    trends_30 = build_daily_investigation_trends(investigations, days=30)
    quality_trends_30 = build_quality_score_trends(
        investigations,
        tool_error_count=count_tool_errors(logs, investigations),
        days=30,
    )

    return {
        "investigations": metrics,
        "quality_score": _quality_block(investigations, logs),
        "period_rates": {
            "last_7_days": compute_period_rates(last_7),
            "last_30_days": compute_period_rates(last_30),
            "all_time": compute_period_rates(investigations),
        },
        "trends": {
            "last_7_days": trends_7,
            "last_30_days": trends_30,
            "quality_score_daily": quality_trends_30,
        },
        "read_only": True,
    }


def get_template_analytics() -> dict[str, Any]:
    investigations = fetch_all_investigations()
    templates = aggregate_template_metrics(investigations)
    return {
        "templates": templates,
        "count": len(templates),
        "read_only": True,
    }


def get_tool_analytics() -> dict[str, Any]:
    investigations = fetch_all_investigations()
    logs = fetch_execution_logs()
    tools = aggregate_tool_metrics(logs, investigations)
    noisiest = sorted(tools, key=lambda t: (-t["failures"], -t["executions"]))[:5]
    return {
        "tools": tools,
        "count": len(tools),
        "noisiest_tools": noisiest,
        "read_only": True,
    }


def get_proposal_analytics() -> dict[str, Any]:
    investigations = fetch_all_investigations()
    proposal_tasks = fetch_proposal_tasks()
    proposals = aggregate_proposal_metrics(investigations, proposal_tasks)
    return {
        "proposals": proposals,
        "proposal_tasks": len(proposal_tasks),
        "read_only": True,
    }


def get_root_cause_analytics() -> dict[str, Any]:
    investigations = fetch_all_investigations()
    root_causes = aggregate_root_cause_metrics(investigations)
    return {
        **root_causes,
        "read_only": True,
    }
