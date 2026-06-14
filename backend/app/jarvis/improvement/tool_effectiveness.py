"""Analyze diagnostic tool effectiveness and generate optimization recommendations."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.jarvis.analytics.aggregation import _TEMPLATE_COLLECTORS
from app.jarvis.investigations.investigation_types import InvestigationStatus

_LOW_UTILITY_RATIO_THRESHOLD = 0.15
_MIN_EXECUTIONS_FOR_ANALYSIS = 3
_HIGH_EXECUTION_THRESHOLD = 10


def _is_successful_investigation(row: dict[str, Any]) -> bool:
    return row.get("status") == InvestigationStatus.COMPLETED.value and float(row.get("confidence") or 0) >= 50


def analyze_tool_effectiveness(
    tool_metrics: list[dict[str, Any]],
    investigations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure tool executions, success rates, and contribution to successful investigations."""
    tool_useful: dict[str, int] = defaultdict(int)
    tool_investigations: dict[str, set[str]] = defaultdict(set)

    terminal = [
        r for r in investigations
        if r.get("status") in {
            InvestigationStatus.COMPLETED.value,
            InvestigationStatus.INSUFFICIENT_EVIDENCE.value,
            InvestigationStatus.PARTIAL_FAILURE.value,
            InvestigationStatus.FAILED.value,
        }
    ]

    for row in terminal:
        template_id = str(row.get("template_id") or "generic")
        collectors = _TEMPLATE_COLLECTORS.get(template_id, _TEMPLATE_COLLECTORS["generic"])
        inv_id = str(row.get("investigation_id") or "")
        successful = _is_successful_investigation(row)
        for tool in collectors:
            tool_investigations[tool].add(inv_id)
            if successful:
                tool_useful[tool] += 1

    effectiveness_rows: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    for tool_row in tool_metrics:
        tool = tool_row["tool"]
        executions = int(tool_row["executions"])
        successes = int(tool_row["successes"])
        failures = int(tool_row["failures"])
        success_rate = float(tool_row["success_rate_pct"])
        useful_outcomes = int(tool_useful.get(tool, 0))
        investigations_using = len(tool_investigations.get(tool, set()))
        utility_ratio = round(useful_outcomes / executions, 3) if executions else 0.0

        effectiveness_rows.append(
            {
                "tool": tool,
                "executions": executions,
                "successes": successes,
                "failures": failures,
                "success_rate_pct": success_rate,
                "useful_outcomes": useful_outcomes,
                "investigations_using": investigations_using,
                "utility_ratio": utility_ratio,
                "average_duration_ms": tool_row.get("average_duration_ms", 0),
                "assessment": _assess_tool(executions, success_rate, utility_ratio, useful_outcomes),
            }
        )

        if executions >= _MIN_EXECUTIONS_FOR_ANALYSIS and utility_ratio < _LOW_UTILITY_RATIO_THRESHOLD:
            recommendations.append(
                {
                    "id": f"tool-low-utility-{tool}",
                    "category": "tool_effectiveness",
                    "impact": "medium" if executions < _HIGH_EXECUTION_THRESHOLD else "high",
                    "frequency": executions,
                    "confidence": min(90.0, 60.0 + (1 - utility_ratio) * 30),
                    "title": f"Review '{tool}' tool priority in investigation templates",
                    "recommendation": (
                        f"Tool '{tool}' ran {executions} times but contributed to only "
                        f"{useful_outcomes} successful investigations "
                        f"(utility ratio: {utility_ratio:.1%}). "
                        f"Lower priority or remove from some templates."
                    ),
                    "reason": f"Low utility ratio ({utility_ratio:.1%}) despite {executions} executions",
                    "evidence": [
                        f"{executions} executions, {successes} successes, {failures} failures",
                        f"{useful_outcomes} useful outcomes in completed investigations",
                        f"Success rate: {success_rate:.1f}%, utility ratio: {utility_ratio:.1%}",
                    ],
                    "expected_benefit": "Reduce investigation runtime and noise from low-value tool calls",
                }
            )

        if executions >= _HIGH_EXECUTION_THRESHOLD and success_rate < 60:
            recommendations.append(
                {
                    "id": f"tool-low-success-{tool}",
                    "category": "tool_effectiveness",
                    "impact": "high",
                    "frequency": executions,
                    "confidence": min(85.0, 50.0 + failures),
                    "title": f"Fix or replace failing '{tool}' tool",
                    "recommendation": (
                        f"Tool '{tool}' has {success_rate:.0f}% success rate across "
                        f"{executions} executions ({failures} failures). "
                        f"Investigate tool reliability or add fallback collectors."
                    ),
                    "reason": f"Low success rate ({success_rate:.1f}%) with high usage",
                    "evidence": [
                        f"{executions} executions, {failures} failures",
                        f"Success rate: {success_rate:.1f}%",
                    ],
                    "expected_benefit": "Improve investigation completion rate and reduce partial failures",
                }
            )

    effectiveness_rows.sort(key=lambda r: (-r["executions"], r["tool"]))
    low_utility = [r for r in effectiveness_rows if r["utility_ratio"] < _LOW_UTILITY_RATIO_THRESHOLD]
    high_value = [r for r in effectiveness_rows if r["utility_ratio"] >= 0.5 and r["executions"] >= 2]

    return {
        "tools": effectiveness_rows,
        "low_utility_tools": low_utility[:10],
        "high_value_tools": high_value[:10],
        "recommendations": recommendations,
        "summary": {
            "tools_analyzed": len(effectiveness_rows),
            "low_utility_count": len(low_utility),
            "high_value_count": len(high_value),
        },
    }


def _assess_tool(
    executions: int,
    success_rate: float,
    utility_ratio: float,
    useful_outcomes: int,
) -> str:
    if executions < _MIN_EXECUTIONS_FOR_ANALYSIS:
        return "insufficient_data"
    if utility_ratio >= 0.5 and success_rate >= 80:
        return "high_value"
    if utility_ratio < _LOW_UTILITY_RATIO_THRESHOLD:
        return "low_utility"
    if success_rate < 60:
        return "unreliable"
    return "moderate"
