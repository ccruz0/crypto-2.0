"""Priority ranking for Jarvis improvement recommendations."""

from __future__ import annotations

from typing import Literal

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


def rank_backlog(items: list[dict]) -> list[dict]:
    """Sort recommendations by priority score descending, stable on title."""
    return sorted(
        items,
        key=lambda item: (-float(item.get("priority_score") or 0), str(item.get("title") or "")),
    )
