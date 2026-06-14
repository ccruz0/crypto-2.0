"""Priority ranking for Jarvis improvement recommendations."""

from __future__ import annotations

from typing import Literal

from app.jarvis.improvement.tool_classification import (
    extract_tool_from_recommendation_id,
    is_workflow_measured_tool,
    should_suppress_workflow_recommendation,
)

PriorityLevel = Literal["high", "medium", "low"]
ImpactLevel = Literal["high", "medium", "low"]

_IMPACT_WEIGHTS: dict[str, float] = {"high": 3.0, "medium": 2.0, "low": 1.0}


def compute_priority_score(*, impact: ImpactLevel, frequency: int, confidence: float) -> float:
    """Priority = Impact × Frequency × Confidence (normalized 0–100)."""
    impact_weight = _IMPACT_WEIGHTS.get(impact, 1.0)
    freq_factor = min(max(frequency, 0), 100) / 10.0
    conf_factor = min(max(confidence, 0.0), 100.0) / 100.0
    return round(impact_weight * freq_factor * conf_factor * 10, 2)


def rank_priority(score: float) -> PriorityLevel:
    if score >= 50:
        return "high"
    if score >= 15:
        return "medium"
    return "low"


def is_workflow_deprecation_recommendation(item: dict) -> bool:
    """True when recommendation suggests removing or deprioritizing a workflow tool."""
    return should_suppress_workflow_recommendation(item)


def filter_suppressed_recommendations(items: list[dict]) -> tuple[list[dict], int]:
    """Remove workflow-tool deprecation recommendations; return kept items and suppressed count."""
    kept: list[dict] = []
    suppressed = 0
    for item in items:
        if should_suppress_workflow_recommendation(item):
            suppressed += 1
            continue
        kept.append(item)
    return kept, suppressed


def apply_orchestration_ranking_cap(item: dict) -> dict:
    """
    Cap priority for any remaining workflow-tool recommendations so diagnostic
    gaps rank above mandatory workflow components.
    """
    tool = extract_tool_from_recommendation_id(str(item.get("id") or ""))
    if tool is None or not is_workflow_measured_tool(tool):
        return item
    score = float(item.get("priority_score") or 0)
    if score >= 50:
        capped = {**item, "priority_score": min(score, 14.0), "priority": "medium"}
        return capped
    return item


def rank_backlog(items: list[dict]) -> list[dict]:
    """Sort recommendations by priority score descending, stable on title."""
    adjusted = [apply_orchestration_ranking_cap(item) for item in items]
    return sorted(
        adjusted,
        key=lambda item: (-float(item.get("priority_score") or 0), str(item.get("title") or "")),
    )
