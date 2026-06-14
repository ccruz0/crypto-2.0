"""Recommendation quality scoring for the Jarvis improvement engine."""

from __future__ import annotations

from typing import Any

from app.jarvis.improvement.tool_classification import (
    extract_tool_from_recommendation_id,
    is_workflow_measured_tool,
    should_suppress_workflow_recommendation,
)


def _normalize_title(title: str) -> str:
    return " ".join(str(title or "").lower().split())


def count_duplicate_recommendations(recommendations: list[dict[str, Any]]) -> int:
    """Count recommendations with duplicate normalized titles."""
    seen: set[str] = set()
    duplicates = 0
    for rec in recommendations:
        key = _normalize_title(str(rec.get("title") or ""))
        if not key:
            continue
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return duplicates


def compute_evidence_coverage(recommendations: list[dict[str, Any]]) -> float:
    if not recommendations:
        return 100.0
    with_evidence = sum(1 for r in recommendations if r.get("evidence"))
    return round(with_evidence / len(recommendations) * 100, 1)


def partition_recommendations(
    raw_recommendations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Return filtered recommendations and suppressed count."""
    kept: list[dict[str, Any]] = []
    suppressed = 0
    for rec in raw_recommendations:
        if should_suppress_workflow_recommendation(rec):
            suppressed += 1
            continue
        kept.append(rec)
    return kept, suppressed


def _workflow_tool_high_priority_share(recommendations: list[dict[str, Any]]) -> float:
    high = [r for r in recommendations if r.get("priority") == "high"]
    if not high:
        return 0.0
    workflow_high = 0
    for rec in high:
        tool = extract_tool_from_recommendation_id(str(rec.get("id") or ""))
        if tool and is_workflow_measured_tool(tool):
            workflow_high += 1
    return workflow_high / len(high)


def compute_quality_score(
    recommendations: list[dict[str, Any]],
    *,
    suppressed_count: int,
    duplicate_count: int,
    evidence_coverage: float,
) -> float:
    """
    Score recommendation quality (0–100).

    Higher when evidence is strong, duplicates are few, and high-priority items
    focus on investigation weaknesses rather than workflow tool deprecation.
    """
    if not recommendations and suppressed_count == 0:
        return 100.0

    total_raw = len(recommendations) + suppressed_count
    suppression_bonus = min(15.0, (suppressed_count / max(total_raw, 1)) * 30)
    duplicate_penalty = min(20.0, duplicate_count * 5)
    workflow_penalty = _workflow_tool_high_priority_share(recommendations) * 25

    score = (
        evidence_coverage * 0.45
        + max(0.0, 55.0 - duplicate_penalty - workflow_penalty)
        + suppression_bonus
    )
    return round(min(100.0, max(0.0, score)), 1)


def build_quality_report(
    raw_recommendations: list[dict[str, Any]],
    finalized_recommendations: list[dict[str, Any]],
    *,
    suppressed_count: int,
) -> dict[str, Any]:
    high_priority = [r for r in finalized_recommendations if r.get("priority") == "high"]
    duplicate_count = count_duplicate_recommendations(finalized_recommendations)
    evidence_coverage = compute_evidence_coverage(finalized_recommendations)
    quality_score = compute_quality_score(
        finalized_recommendations,
        suppressed_count=suppressed_count,
        duplicate_count=duplicate_count,
        evidence_coverage=evidence_coverage,
    )
    return {
        "quality_score": quality_score,
        "recommendation_count": len(finalized_recommendations),
        "high_priority_count": len(high_priority),
        "suppressed_recommendations": suppressed_count,
        "duplicate_recommendations": duplicate_count,
        "evidence_coverage": evidence_coverage,
        "read_only": True,
    }
