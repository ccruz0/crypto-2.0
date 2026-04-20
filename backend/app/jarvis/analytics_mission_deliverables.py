"""Inferred read-only analytics mission shape (heuristic; no new planner format)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.jarvis.analytics_prompt_gates import (
    detect_readonly_analytics_domain,
    explicit_timeframe_in_prompt,
    explicit_top_rank_in_prompt,
    extract_explicit_timeframe_phrase,
    extract_explicit_top_rank,
    readonly_analytics_prompt_sufficient,
)


@dataclass(frozen=True)
class AnalyticsMissionSpec:
    """Internal mission deliverables for strict read-only analytics evaluation."""

    domain: str  # google_ads | ga4 | gsc
    timeframe_label: str
    top_rank: int | None
    requested_metrics_tokens: tuple[str, ...]
    inferred_timeframe: bool = False
    inferred_top_rank: bool = False


def _metric_tokens_for_domain(domain: str, prompt: str) -> tuple[str, ...]:
    low = (prompt or "").lower()
    if domain == "google_ads":
        pat = re.compile(
            r"\b(spend|impressions?|clicks?|ctr|conversions?|cost|roas|campaigns?|metrics|"
            r"campa[nñ]as?|m[ée]tricas?|gasto|conversiones?|clics?|impresiones?)\b",
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
    For underspecified Google Ads read-only analytics, applies last 30 days and top 10 when
    the prompt omits an explicit window or rank (see inferred_* flags).
    """
    text = (prompt or "").strip()
    if not readonly_analytics_prompt_sufficient(text):
        return None
    domain = detect_readonly_analytics_domain(text)
    if not domain:
        return None

    ex_time = explicit_timeframe_in_prompt(text)
    ex_top = explicit_top_rank_in_prompt(text)
    timeframe_label = extract_explicit_timeframe_phrase(text) or "unspecified_window"
    top_rank = extract_explicit_top_rank(text)
    inferred_timeframe = False
    inferred_top_rank = False

    if domain == "google_ads":
        if not ex_time:
            timeframe_label = "last 30 days"
            inferred_timeframe = True
        if not ex_top:
            top_rank = 10
            inferred_top_rank = True

    return AnalyticsMissionSpec(
        domain=domain,
        timeframe_label=timeframe_label,
        top_rank=top_rank,
        requested_metrics_tokens=_metric_tokens_for_domain(domain, text),
        inferred_timeframe=inferred_timeframe,
        inferred_top_rank=inferred_top_rank,
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
            inferred_timeframe=bool(raw.get("inferred_timeframe")),
            inferred_top_rank=bool(raw.get("inferred_top_rank")),
        )
    except (TypeError, ValueError):
        return None


def deliverables_to_dict(spec: AnalyticsMissionSpec) -> dict[str, Any]:
    return {
        "domain": spec.domain,
        "timeframe_label": spec.timeframe_label,
        "top_rank": spec.top_rank,
        "requested_metrics_tokens": list(spec.requested_metrics_tokens),
        "inferred_timeframe": spec.inferred_timeframe,
        "inferred_top_rank": spec.inferred_top_rank,
    }
