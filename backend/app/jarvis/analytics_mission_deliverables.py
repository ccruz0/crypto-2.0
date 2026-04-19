"""Inferred read-only analytics mission shape (heuristic; no new planner format)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.jarvis.analytics_prompt_gates import (
    detect_readonly_analytics_domain,
    readonly_analytics_prompt_sufficient,
)

_TIME_SCOPE = re.compile(
    r"\b(last|past|previous)\s+\d+\s*(days?|weeks?|months?)\b",
    re.IGNORECASE,
)
_TOP_RANK = re.compile(r"\btop\s+(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class AnalyticsMissionSpec:
    """Internal mission deliverables for strict read-only analytics evaluation."""

    domain: str  # google_ads | ga4 | gsc
    timeframe_label: str
    top_rank: int | None
    requested_metrics_tokens: tuple[str, ...]


def _timeframe_from_prompt(prompt: str) -> str:
    m = _TIME_SCOPE.search(prompt or "")
    if m:
        return m.group(0).lower().replace("  ", " ")
    return "unspecified_window"


def _top_rank_from_prompt(prompt: str) -> int | None:
    m = _TOP_RANK.search(prompt or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _metric_tokens_for_domain(domain: str, prompt: str) -> tuple[str, ...]:
    low = (prompt or "").lower()
    if domain == "google_ads":
        pat = re.compile(
            r"\b(spend|impressions?|clicks?|ctr|conversions?|cost|roas|campaigns?|metrics)\b",
            re.IGNORECASE,
        )
    elif domain == "ga4":
        pat = re.compile(
            r"\b(pages?|events?|sessions?|users?|metrics|conversions?|clicks?|impressions?|engagement|traffic)\b",
            re.IGNORECASE,
        )
    else:
        pat = re.compile(
            r"\b(queries?|pages?|clicks?|impressions?|ctr|position|metrics|search)\b",
            re.IGNORECASE,
        )
    return tuple(sorted(set(m.group(0).lower() for m in pat.finditer(low))))


def infer_analytics_deliverables(prompt: str) -> AnalyticsMissionSpec | None:
    """
    Infer deliverables for strict rubric evaluation.

    Returns None when the prompt does not pass readonly_analytics_prompt_sufficient.
    """
    text = (prompt or "").strip()
    if not readonly_analytics_prompt_sufficient(text):
        return None
    domain = detect_readonly_analytics_domain(text)
    if not domain:
        return None
    return AnalyticsMissionSpec(
        domain=domain,
        timeframe_label=_timeframe_from_prompt(text),
        top_rank=_top_rank_from_prompt(text),
        requested_metrics_tokens=_metric_tokens_for_domain(domain, text),
    )


def spec_from_goal_eval(goal_eval: dict[str, Any]) -> AnalyticsMissionSpec | None:
    """Reconstruct spec for corrective retry from goal_eval payload (set by evaluate_goal_satisfaction)."""
    raw = goal_eval.get("deliverables")
    if not isinstance(raw, dict):
        return None
    try:
        return AnalyticsMissionSpec(
            domain=str(raw.get("domain") or ""),
            timeframe_label=str(raw.get("timeframe_label") or ""),
            top_rank=raw.get("top_rank") if raw.get("top_rank") is not None else None,
            requested_metrics_tokens=tuple(raw.get("requested_metrics_tokens") or ()),
        )
    except (TypeError, ValueError):
        return None


def deliverables_to_dict(spec: AnalyticsMissionSpec) -> dict[str, Any]:
    return {
        "domain": spec.domain,
        "timeframe_label": spec.timeframe_label,
        "top_rank": spec.top_rank,
        "requested_metrics_tokens": list(spec.requested_metrics_tokens),
    }
