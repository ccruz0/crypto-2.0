"""Detect investigation quality trends and recurring incident patterns."""

from __future__ import annotations

from typing import Any

from app.jarvis.analytics.aggregation import is_false_positive
from app.jarvis.analytics.trend_analysis import build_quality_score_trends, compute_period_rates
from app.jarvis.analytics.aggregation import filter_rows_since, compute_quality_score, count_tool_errors
from app.jarvis.investigations.investigation_types import InvestigationStatus


def analyze_quality_trends(
    investigations: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    root_cause_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Detect quality score changes, recurring incidents, and false-positive trends."""
    tool_errors = count_tool_errors(logs, investigations)
    overall_score = compute_quality_score(investigations, tool_errors=tool_errors)

    last_7 = filter_rows_since(investigations, 7)
    last_30 = filter_rows_since(investigations, 30)
    last_7_ids = {r.get("investigation_id") for r in last_7}
    prev_7 = [r for r in filter_rows_since(investigations, 14) if r.get("investigation_id") not in last_7_ids]

    logs_7 = filter_rows_since(logs, 7)
    logs_30 = filter_rows_since(logs, 30)
    logs_prev_7 = filter_rows_since(logs, 14)

    score_7 = compute_quality_score(last_7, tool_errors=count_tool_errors(logs_7, last_7))
    score_30 = compute_quality_score(last_30, tool_errors=count_tool_errors(logs_30, last_30))
    score_prev_7 = compute_quality_score(prev_7, tool_errors=count_tool_errors(logs_prev_7, prev_7)) if prev_7 else score_7

    score_delta_7d = round(score_7 - score_prev_7, 1)
    trend_direction = "improving" if score_delta_7d > 2 else "declining" if score_delta_7d < -2 else "stable"

    quality_daily = build_quality_score_trends(
        investigations,
        tool_error_count=tool_errors,
        days=30,
    )

    rates_7 = compute_period_rates(last_7)
    rates_30 = compute_period_rates(last_30)
    rates_all = compute_period_rates(investigations)

    false_positives_total = sum(1 for r in investigations if is_false_positive(r))
    false_positives_7 = sum(1 for r in last_7 if is_false_positive(r))
    fp_rate_7 = rates_7.get("false_positive_rate_pct", 0.0)
    fp_rate_30 = rates_30.get("false_positive_rate_pct", 0.0)

    recurring = root_cause_metrics.get("recurring_incidents") or []
    recurring_filtered = [r for r in recurring if int(r.get("occurrences") or 0) >= 2]

    open_orders_count = sum(
        1 for r in investigations
        if "open_orders" in str(r.get("template_id") or "")
        or "order" in str(r.get("objective") or "").lower()
    )
    open_orders_pct = round(open_orders_count / len(investigations) * 100, 1) if investigations else 0.0

    recommendations: list[dict[str, Any]] = []

    if trend_direction == "declining":
        recommendations.append(
            {
                "id": "trend-quality-declining",
                "category": "quality_trend",
                "impact": "high",
                "frequency": len(last_7),
                "confidence": min(90.0, abs(score_delta_7d) * 10),
                "title": "Investigation quality score is declining",
                "recommendation": (
                    f"Quality score dropped {abs(score_delta_7d):.1f} points over the last 7 days "
                    f"(current: {score_7:.1f}, previous period: {score_prev_7:.1f}). "
                    f"Review recent failed and insufficient_evidence investigations."
                ),
                "reason": f"7-day quality delta: {score_delta_7d:+.1f}",
                "evidence": [
                    f"Overall score: {overall_score:.1f}",
                    f"Last 7 days: {score_7:.1f} (was {score_prev_7:.1f})",
                    f"Last 30 days: {score_30:.1f}",
                ],
                "expected_benefit": "Restore quality score to prior baseline",
            }
        )

    if fp_rate_7 > 15 or (false_positives_7 >= 2 and len(last_7) >= 3):
        recommendations.append(
            {
                "id": "trend-false-positives",
                "category": "quality_trend",
                "impact": "high" if fp_rate_7 > 25 else "medium",
                "frequency": false_positives_7 or false_positives_total,
                "confidence": min(85.0, fp_rate_7 + 30),
                "title": "False-positive investigation trend detected",
                "recommendation": (
                    f"False-positive rate is {fp_rate_7:.1f}% (7d) / {fp_rate_30:.1f}% (30d). "
                    f"Tighten template matching and add pre-check collectors to avoid "
                    f"investigations that conclude 'no action required'."
                ),
                "reason": f"Elevated false-positive rate ({fp_rate_7:.1f}% last 7 days)",
                "evidence": [
                    f"{false_positives_total} false positives all-time",
                    f"{false_positives_7} false positives in last 7 days",
                    f"7d rate: {fp_rate_7:.1f}%, 30d rate: {fp_rate_30:.1f}%",
                ],
                "expected_benefit": "Reduce wasted investigation cycles by 20–40%",
            }
        )

    for incident in recurring_filtered[:5]:
        occurrences = int(incident.get("occurrences") or 0)
        root = str(incident.get("root_cause") or incident.get("key") or "unknown")
        if occurrences >= 2:
            recommendations.append(
                {
                    "id": f"trend-recurring-{incident.get('key', root)[:40]}",
                    "category": "quality_trend",
                    "impact": "high" if occurrences >= 4 else "medium",
                    "frequency": occurrences,
                    "confidence": min(95.0, 50.0 + occurrences * 10),
                    "title": f"Recurring incident: {root[:80]}",
                    "recommendation": (
                        f"Root cause '{root}' has recurred {occurrences} times. "
                        f"Consider a permanent fix proposal or dedicated runbook template."
                    ),
                    "reason": f"Recurring root cause ({occurrences} occurrences)",
                    "evidence": [
                        f"Root cause: {root}",
                        f"Occurrences: {occurrences}",
                    ],
                    "expected_benefit": "Prevent repeat investigations for the same underlying issue",
                }
            )

    if open_orders_pct >= 40 and len(investigations) >= 5:
        recommendations.append(
            {
                "id": "trend-open-orders-dominance",
                "category": "quality_trend",
                "impact": "high",
                "frequency": open_orders_count,
                "confidence": 80.0,
                "title": "Open-order investigations dominate incident volume",
                "recommendation": (
                    f"Open-order investigations account for {open_orders_pct:.0f}% of incidents "
                    f"({open_orders_count}/{len(investigations)}). "
                    f"Create dedicated advanced-order collector and trigger-order diagnostics."
                ),
                "reason": f"Open-order share: {open_orders_pct:.0f}%",
                "evidence": [
                    f"{open_orders_count} of {len(investigations)} investigations relate to orders",
                    f"Share: {open_orders_pct:.0f}%",
                ],
                "expected_benefit": "Reduce false positives by ~30% on order-related incidents",
            }
        )

    failed_recent = sum(
        1 for r in last_7
        if r.get("status") in (InvestigationStatus.FAILED.value, InvestigationStatus.PARTIAL_FAILURE.value)
    )
    if failed_recent >= 2:
        recommendations.append(
            {
                "id": "trend-recent-failures",
                "category": "quality_trend",
                "impact": "high",
                "frequency": failed_recent,
                "confidence": 75.0,
                "title": "Recent investigation failures need attention",
                "recommendation": (
                    f"{failed_recent} investigations failed or partially failed in the last 7 days. "
                    f"Review collector reliability and mandatory tool configuration."
                ),
                "reason": f"{failed_recent} failures/partial failures in last 7 days",
                "evidence": [f"{failed_recent} failed/partial_failure in last 7 days"],
                "expected_benefit": "Improve completion rate and evidence quality",
            }
        )

    return {
        "quality_scores": {
            "overall": overall_score,
            "last_7_days": score_7,
            "last_30_days": score_30,
            "previous_7_days": score_prev_7,
            "delta_7d": score_delta_7d,
            "trend_direction": trend_direction,
        },
        "false_positives": {
            "total": false_positives_total,
            "last_7_days": false_positives_7,
            "rate_7d_pct": fp_rate_7,
            "rate_30d_pct": fp_rate_30,
            "rate_all_time_pct": rates_all.get("false_positive_rate_pct", 0.0),
        },
        "period_rates": {
            "last_7_days": rates_7,
            "last_30_days": rates_30,
            "all_time": rates_all,
        },
        "recurring_incidents": recurring_filtered,
        "open_orders_share_pct": open_orders_pct,
        "quality_score_daily": quality_daily,
        "recommendations": recommendations,
    }
