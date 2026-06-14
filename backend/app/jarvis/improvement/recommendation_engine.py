"""Orchestrate Jarvis self-improvement analysis and generate ranked recommendations."""

from __future__ import annotations

from typing import Any

from app.jarvis.analytics.aggregation import (
    aggregate_root_cause_metrics,
    aggregate_template_metrics,
    aggregate_tool_metrics,
    fetch_all_investigations,
    fetch_execution_logs,
)
from app.jarvis.improvement.quality_trends import analyze_quality_trends
from app.jarvis.improvement.recommendation_quality import build_quality_report
from app.jarvis.improvement.recommendation_ranker import (
    compute_priority_score,
    filter_suppressed_recommendations,
    rank_backlog,
    rank_priority,
)
from app.jarvis.improvement.template_gap_analysis import analyze_template_gaps
from app.jarvis.improvement.tool_effectiveness import analyze_tool_effectiveness


def _finalize_recommendation(raw: dict[str, Any]) -> dict[str, Any]:
    impact = raw.get("impact", "medium")
    frequency = int(raw.get("frequency") or 0)
    confidence = float(raw.get("confidence") or 50.0)
    score = compute_priority_score(impact=impact, frequency=frequency, confidence=confidence)
    return {
        **raw,
        "impact": impact,
        "frequency": frequency,
        "confidence": round(confidence, 1),
        "priority_score": score,
        "priority": rank_priority(score),
    }


def _collect_raw_recommendations(
    template_analysis: dict[str, Any],
    tool_analysis: dict[str, Any],
    trend_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    raw.extend(template_analysis.get("recommendations") or [])
    raw.extend(tool_analysis.get("recommendations") or [])
    raw.extend(trend_analysis.get("recommendations") or [])
    return raw


def _collect_all_recommendations(
    template_analysis: dict[str, Any],
    tool_analysis: dict[str, Any],
    trend_analysis: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    raw = _collect_raw_recommendations(template_analysis, tool_analysis, trend_analysis)

    seen_ids: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in raw:
        rec_id = str(item.get("id") or "")
        if rec_id and rec_id in seen_ids:
            continue
        if rec_id:
            seen_ids.add(rec_id)
        unique.append(_finalize_recommendation(item))

    filtered, suppressed = filter_suppressed_recommendations(unique)
    return rank_backlog(filtered), suppressed


def _run_analyses() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    investigations = fetch_all_investigations()
    logs = fetch_execution_logs()
    template_metrics = aggregate_template_metrics(investigations)
    tool_metrics = aggregate_tool_metrics(logs, investigations)
    root_causes = aggregate_root_cause_metrics(investigations)

    template_analysis = analyze_template_gaps(investigations, template_metrics)
    tool_analysis = analyze_tool_effectiveness(tool_metrics, investigations)
    trend_analysis = analyze_quality_trends(investigations, logs, root_causes)
    return template_analysis, tool_analysis, trend_analysis, investigations


def get_improvement_recommendations() -> dict[str, Any]:
    """Generate full ranked recommendation set and improvement backlog."""
    template_analysis, tool_analysis, trend_analysis, _ = _run_analyses()
    recommendations, suppressed = _collect_all_recommendations(
        template_analysis, tool_analysis, trend_analysis
    )
    high = [r for r in recommendations if r["priority"] == "high"]
    medium = [r for r in recommendations if r["priority"] == "medium"]
    low = [r for r in recommendations if r["priority"] == "low"]

    return {
        "recommendations": recommendations,
        "backlog": recommendations,
        "by_priority": {"high": high, "medium": medium, "low": low},
        "counts": {
            "total": len(recommendations),
            "high": len(high),
            "medium": len(medium),
            "low": len(low),
            "suppressed": suppressed,
        },
        "read_only": True,
    }


def get_improvement_quality() -> dict[str, Any]:
    """Return recommendation quality metrics for the improvement engine."""
    template_analysis, tool_analysis, trend_analysis, _ = _run_analyses()
    raw = _collect_raw_recommendations(template_analysis, tool_analysis, trend_analysis)
    recommendations, suppressed_count = _collect_all_recommendations(
        template_analysis, tool_analysis, trend_analysis
    )
    return build_quality_report(raw, recommendations, suppressed_count=suppressed_count)


def get_improvement_templates() -> dict[str, Any]:
    """Template gap analysis with ranked gap recommendations."""
    investigations = fetch_all_investigations()
    template_metrics = aggregate_template_metrics(investigations)
    analysis = analyze_template_gaps(investigations, template_metrics)
    recommendations = [_finalize_recommendation(r) for r in analysis.get("recommendations") or []]
    filtered, _ = filter_suppressed_recommendations(recommendations)
    return {
        "gaps": analysis.get("gaps") or [],
        "recommendations": rank_backlog(filtered),
        "summary": analysis.get("summary") or {},
        "template_metrics": template_metrics,
        "read_only": True,
    }


def get_improvement_tools() -> dict[str, Any]:
    """Tool effectiveness analysis with optimization recommendations."""
    investigations = fetch_all_investigations()
    logs = fetch_execution_logs()
    tool_metrics = aggregate_tool_metrics(logs, investigations)
    analysis = analyze_tool_effectiveness(tool_metrics, investigations)
    recommendations = [_finalize_recommendation(r) for r in analysis.get("recommendations") or []]
    filtered, suppressed = filter_suppressed_recommendations(recommendations)
    return {
        "tools": analysis.get("tools") or [],
        "low_utility_tools": analysis.get("low_utility_tools") or [],
        "high_value_tools": analysis.get("high_value_tools") or [],
        "recommendations": rank_backlog(filtered),
        "summary": {**(analysis.get("summary") or {}), "suppressed_recommendations": suppressed},
        "read_only": True,
    }


def get_improvement_trends() -> dict[str, Any]:
    """Quality trend analysis with incident pattern recommendations."""
    investigations = fetch_all_investigations()
    logs = fetch_execution_logs()
    root_causes = aggregate_root_cause_metrics(investigations)
    analysis = analyze_quality_trends(investigations, logs, root_causes)
    recommendations = [_finalize_recommendation(r) for r in analysis.get("recommendations") or []]
    filtered, _ = filter_suppressed_recommendations(recommendations)
    return {
        "quality_scores": analysis.get("quality_scores") or {},
        "false_positives": analysis.get("false_positives") or {},
        "period_rates": analysis.get("period_rates") or {},
        "recurring_incidents": analysis.get("recurring_incidents") or [],
        "open_orders_share_pct": analysis.get("open_orders_share_pct", 0.0),
        "quality_score_daily": analysis.get("quality_score_daily") or [],
        "recommendations": rank_backlog(filtered),
        "read_only": True,
    }
