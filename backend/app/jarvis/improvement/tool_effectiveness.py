"""Analyze diagnostic tool effectiveness and generate optimization recommendations."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.jarvis.analytics.aggregation import _TEMPLATE_COLLECTORS, is_false_positive
from app.jarvis.improvement.tool_classification import (
    classify_tool,
    get_assessment_display,
    is_diagnostic_measured_tool,
    is_workflow_measured_tool,
    is_workflow_protected_tool,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus

_LOW_UTILITY_RATIO_THRESHOLD = 0.15
_MIN_EXECUTIONS_FOR_ANALYSIS = 3
_HIGH_EXECUTION_THRESHOLD = 10
_ABNORMAL_FAILURE_RATE_PCT = 20.0
_SLOW_EXECUTION_MS = 5000
_HIGH_FAILURE_ASSOCIATION_RATE = 0.35


def _is_successful_investigation(row: dict[str, Any]) -> bool:
    return row.get("status") == InvestigationStatus.COMPLETED.value and float(row.get("confidence") or 0) >= 50


def _compute_orchestration_metrics(
    tool: str,
    tool_row: dict[str, Any],
    investigations: list[dict[str, Any]],
    tool_investigations: set[str],
) -> dict[str, float]:
    executions = int(tool_row["executions"])
    successes = int(tool_row["successes"])
    failures = int(tool_row["failures"])
    terminal_count = max(
        len(
            [
                r
                for r in investigations
                if r.get("status")
                in {
                    InvestigationStatus.COMPLETED.value,
                    InvestigationStatus.INSUFFICIENT_EVIDENCE.value,
                    InvestigationStatus.PARTIAL_FAILURE.value,
                    InvestigationStatus.FAILED.value,
                }
            ]
        ),
        1,
    )
    workflow_usage_rate = round(min(executions / terminal_count, 1.0), 3)
    successful_completion_rate = round(successes / executions, 3) if executions else 0.0
    failure_association_rate = round(failures / executions, 3) if executions else 0.0

    failed_inv_ids = {
        str(r.get("investigation_id") or "")
        for r in investigations
        if r.get("status")
        in (InvestigationStatus.FAILED.value, InvestigationStatus.PARTIAL_FAILURE.value)
    }
    if tool_investigations and failed_inv_ids:
        failure_association_rate = round(
            len(tool_investigations & failed_inv_ids) / len(tool_investigations),
            3,
        )

    return {
        "workflow_usage_rate": workflow_usage_rate,
        "successful_completion_rate": successful_completion_rate,
        "failure_association_rate": failure_association_rate,
    }


def _compute_diagnostic_metrics(
    tool: str,
    executions: int,
    useful_outcomes: int,
    investigations: list[dict[str, Any]],
    tool_investigations: set[str],
) -> dict[str, Any]:
    utility_ratio = round(useful_outcomes / executions, 3) if executions else 0.0
    false_positive_contribution = 0
    for row in investigations:
        inv_id = str(row.get("investigation_id") or "")
        if inv_id not in tool_investigations:
            continue
        if is_false_positive(row):
            false_positive_contribution += 1
    return {
        "utility_ratio": utility_ratio,
        "useful_findings": useful_outcomes,
        "false_positive_contribution": false_positive_contribution,
    }


def analyze_tool_effectiveness(
    tool_metrics: list[dict[str, Any]],
    investigations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure tool executions, success rates, and contribution to successful investigations."""
    tool_useful: dict[str, int] = defaultdict(int)
    tool_investigations: dict[str, set[str]] = defaultdict(set)

    terminal = [
        r
        for r in investigations
        if r.get("status")
        in {
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
        for collector_tool in collectors:
            tool_investigations[collector_tool].add(inv_id)
            if successful:
                tool_useful[collector_tool] += 1

    effectiveness_rows: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    for tool_row in tool_metrics:
        tool = tool_row["tool"]
        executions = int(tool_row["executions"])
        successes = int(tool_row["successes"])
        failures = int(tool_row["failures"])
        success_rate = float(tool_row["success_rate_pct"])
        failure_rate = float(tool_row.get("failure_rate_pct") or 0)
        useful_outcomes = int(tool_useful.get(tool, 0))
        investigations_using = len(tool_investigations.get(tool, set()))
        category = classify_tool(tool)
        assessment_display = get_assessment_display(category)

        row_data: dict[str, Any] = {
            "tool": tool,
            "category": category,
            "assessment_display": assessment_display,
            "executions": executions,
            "successes": successes,
            "failures": failures,
            "success_rate_pct": success_rate,
            "useful_outcomes": useful_outcomes,
            "investigations_using": investigations_using,
            "average_duration_ms": tool_row.get("average_duration_ms", 0),
        }

        if is_workflow_measured_tool(tool):
            orch_metrics = _compute_orchestration_metrics(
                tool, tool_row, investigations, tool_investigations.get(tool, set())
            )
            row_data.update(orch_metrics)
            row_data["utility_ratio"] = 0.0
            row_data["useful_findings"] = 0
            row_data["false_positive_contribution"] = 0
            row_data["assessment"] = _assess_workflow_tool(
                executions,
                success_rate,
                orch_metrics["workflow_usage_rate"],
                orch_metrics["failure_association_rate"],
            )
            recommendations.extend(
                _workflow_tool_recommendations(
                    tool=tool,
                    executions=executions,
                    successes=successes,
                    failures=failures,
                    success_rate=success_rate,
                    failure_rate=failure_rate,
                    avg_duration=float(tool_row.get("average_duration_ms") or 0),
                    orch_metrics=orch_metrics,
                )
            )
        else:
            diag_metrics = _compute_diagnostic_metrics(
                tool, executions, useful_outcomes, investigations, tool_investigations.get(tool, set())
            )
            row_data.update(diag_metrics)
            row_data["assessment"] = _assess_diagnostic_tool(
                executions,
                success_rate,
                diag_metrics["utility_ratio"],
                useful_outcomes,
            )
            recommendations.extend(
                _diagnostic_tool_recommendations(
                    tool=tool,
                    executions=executions,
                    successes=successes,
                    failures=failures,
                    success_rate=success_rate,
                    useful_outcomes=useful_outcomes,
                    utility_ratio=diag_metrics["utility_ratio"],
                    avg_duration=float(tool_row.get("average_duration_ms") or 0),
                )
            )

        effectiveness_rows.append(row_data)

    effectiveness_rows.sort(key=lambda r: (-r["executions"], r["tool"]))
    low_utility = [
        r
        for r in effectiveness_rows
        if is_diagnostic_measured_tool(r["tool"])
        and r.get("utility_ratio", 0) < _LOW_UTILITY_RATIO_THRESHOLD
        and r["executions"] >= _MIN_EXECUTIONS_FOR_ANALYSIS
    ]
    high_value = [
        r
        for r in effectiveness_rows
        if is_diagnostic_measured_tool(r["tool"])
        and r.get("utility_ratio", 0) >= 0.5
        and r["executions"] >= 2
    ]

    return {
        "tools": effectiveness_rows,
        "low_utility_tools": low_utility[:10],
        "high_value_tools": high_value[:10],
        "recommendations": recommendations,
        "summary": {
            "tools_analyzed": len(effectiveness_rows),
            "low_utility_count": len(low_utility),
            "high_value_count": len(high_value),
            "workflow_tools": sum(1 for r in effectiveness_rows if is_workflow_measured_tool(r["tool"])),
            "diagnostic_tools": sum(1 for r in effectiveness_rows if is_diagnostic_measured_tool(r["tool"])),
        },
    }


def _assess_workflow_tool(
    executions: int,
    success_rate: float,
    workflow_usage_rate: float,
    failure_association_rate: float,
) -> str:
    if executions < _MIN_EXECUTIONS_FOR_ANALYSIS:
        return "insufficient_data"
    if success_rate < 60 or failure_association_rate >= _HIGH_FAILURE_ASSOCIATION_RATE:
        return "unreliable"
    if workflow_usage_rate >= 0.5 and success_rate >= 80:
        return "workflow_healthy"
    if workflow_usage_rate < 0.1:
        return "low_participation"
    return "workflow_active"


def _assess_diagnostic_tool(
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


def _workflow_tool_recommendations(
    *,
    tool: str,
    executions: int,
    successes: int,
    failures: int,
    success_rate: float,
    failure_rate: float,
    avg_duration: float,
    orch_metrics: dict[str, float],
) -> list[dict[str, Any]]:
    """Only recommend workflow tool changes for abnormal failure, correlation, or slowness."""
    if executions < _MIN_EXECUTIONS_FOR_ANALYSIS:
        return []

    recs: list[dict[str, Any]] = []
    failure_assoc = orch_metrics["failure_association_rate"]

    if failure_rate >= _ABNORMAL_FAILURE_RATE_PCT or success_rate < 60:
        recs.append(
            {
                "id": f"tool-failure-{tool}",
                "category": "tool_effectiveness",
                "impact": "high",
                "frequency": executions,
                "confidence": min(90.0, 55.0 + failures * 2),
                "title": f"Investigate abnormal failure rate for workflow tool '{tool}'",
                "recommendation": (
                    f"Workflow tool '{tool}' has an abnormal {success_rate:.0f}% success rate "
                    f"across {executions} executions ({failures} failures). "
                    f"Review error handling and retry logic for this mandatory workflow step."
                ),
                "reason": f"Abnormal tool failure rate ({failure_rate:.1f}%) for workflow component",
                "evidence": [
                    f"{executions} executions, {failures} failures",
                    f"Success rate: {success_rate:.1f}%",
                    f"Failure association rate: {failure_assoc:.1%}",
                ],
                "expected_benefit": "Restore reliable investigation workflow completion",
            }
        )

    if failure_assoc >= _HIGH_FAILURE_ASSOCIATION_RATE and executions >= _MIN_EXECUTIONS_FOR_ANALYSIS:
        recs.append(
            {
                "id": f"tool-investigation-failure-{tool}",
                "category": "tool_effectiveness",
                "impact": "high",
                "frequency": int(failure_assoc * executions),
                "confidence": min(88.0, 50.0 + failure_assoc * 40),
                "title": f"Workflow tool '{tool}' correlates with investigation failures",
                "recommendation": (
                    f"Tool '{tool}' is associated with investigation failures "
                    f"(failure association rate: {failure_assoc:.1%}). "
                    f"Audit this workflow step for timeout, dependency, or sequencing issues."
                ),
                "reason": f"High failure association ({failure_assoc:.1%}) with failed investigations",
                "evidence": [
                    f"{executions} workflow executions",
                    f"Failure association rate: {failure_assoc:.1%}",
                    f"Successful completion rate: {orch_metrics['successful_completion_rate']:.1%}",
                ],
                "expected_benefit": "Reduce investigation failures caused by workflow step errors",
            }
        )

    if avg_duration >= _SLOW_EXECUTION_MS and executions >= _MIN_EXECUTIONS_FOR_ANALYSIS:
        recs.append(
            {
                "id": f"tool-slow-{tool}",
                "category": "tool_effectiveness",
                "impact": "medium",
                "frequency": executions,
                "confidence": min(80.0, 45.0 + (avg_duration / 1000)),
                "title": f"Workflow tool '{tool}' significantly slows investigation execution",
                "recommendation": (
                    f"Workflow tool '{tool}' averages {avg_duration:.0f}ms per execution "
                    f"across {executions} runs. Optimize or parallelize this mandatory step."
                ),
                "reason": f"High average duration ({avg_duration:.0f}ms) for workflow tool",
                "evidence": [
                    f"Average duration: {avg_duration:.0f}ms",
                    f"{executions} executions",
                    f"Workflow usage rate: {orch_metrics['workflow_usage_rate']:.1%}",
                ],
                "expected_benefit": "Faster end-to-end investigation turnaround",
            }
        )

    return recs


def _diagnostic_tool_recommendations(
    *,
    tool: str,
    executions: int,
    successes: int,
    failures: int,
    success_rate: float,
    useful_outcomes: int,
    utility_ratio: float,
    avg_duration: float,
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []

    if executions >= _MIN_EXECUTIONS_FOR_ANALYSIS and utility_ratio < _LOW_UTILITY_RATIO_THRESHOLD:
        if is_workflow_protected_tool(tool):
            return recs
        recs.append(
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
        recs.append(
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

    return recs
