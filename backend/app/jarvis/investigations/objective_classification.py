"""Objective-aware investigation classification and plan templates for Jarvis."""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any

# Plan step: (step_id, action, tool, description)
PlanStep = tuple[str, str, str, str]


class InvestigationObjectiveType(str, Enum):
    ORDER_RECONCILIATION = "order_reconciliation"
    DEPLOYMENT_HEALTH = "deployment_health"
    REPOSITORY_ANALYSIS = "repository_analysis"
    ALERT_INVESTIGATION = "alert_investigation"
    SIGNAL_MONITOR_INVESTIGATION = "signal_monitor_investigation"
    EXCHANGE_AUTH_INVESTIGATION = "exchange_auth_investigation"
    GENERIC_INVESTIGATION = "generic_investigation"


def _normalize_objective_text(text: str) -> str:
    """Lowercase and strip accents for keyword matching."""
    lowered = (text or "").lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


# Order reconciliation — checked before generic "jarvis" / "architecture" patterns.
_ORDER_RECONCILIATION_PATTERN = re.compile(
    r"open\s+orders?|"
    r"ordenes?\s+abiertas?|"
    r"ordenes?\s+(?:que\s+)?no\s+aparecen|"
    r"ordenes?\s+faltantes?|"
    r"why\s+are\s+open\s+orders|"
    r"why\s+does\s+dashboard\s+differ|"
    r"why\s+are\s+open\s+orders\s+different|"
    r"open\s+orders?\s+(?:are\s+)?different|"
    r"open\s+orders?\s+not\s+match(?:ing)?|"
    r"(?:open\s+)?orders?\s+missing(?:\s+from)?(?:\s+(?:crypto\.?com|dashboard|exchange|wallet))?|"
    r"executed\s+orders?\s+(?:is\s+)?missing|executed\s+orders?\s+not\s+(?:visible|showing)|"
    r"wallet\s+orders?\s+(?:are\s+)?not\s+visible|"
    r"crypto\.?com\s+shows?\s+(?:more\s+)?orders?|"
    r"dashboard\s+(?:missing\s+orders?|not\s+match(?:ing)?\s+exchange)|"
    r"not\s+all(?:\s+(?:my\s+)?)?open\s+orders?|"
    r"missing\s+trigger\s+orders?|trigger\s+orders?\s+not\s+show(?:ing)?|"
    r"order\s+mismatch|"
    r"reconcil(?:e|iation)|"
    r"exchange_sync|"
    r"(?:exchange|dashboard).*(?:mismatch|different|discrepanc)|"
    r"(?:no\s+)?aparecen\s+(?:en\s+)?(?:el\s+)?dashboard|"
    r"exchange.*dashboard|dashboard.*exchange",
    re.IGNORECASE,
)

_ALERT_INVESTIGATION_PATTERN = re.compile(
    r"\b(?:critical|high|warning)\b.*\balert|\balert(?:s)?\b|"
    r"prometheus|telegram\s+alert|investigation\s+alert",
    re.IGNORECASE,
)

_EXCHANGE_AUTH_PATTERN = re.compile(
    r"exchange\s+auth|crypto\.?com\s+auth|authentication\s+fail|40101|"
    r"api\s+credential|auth\s+error|credenciales",
    re.IGNORECASE,
)

_SIGNAL_MONITOR_PATTERN = re.compile(
    r"\bsignal(?:s)?\b|\bmonitor(?:ing)?\b|trading\s+signal|alert\s+signal",
    re.IGNORECASE,
)

_DEPLOYMENT_HEALTH_PATTERN = re.compile(
    r"deploy(?:ment)?|container|docker|running|health\s+check|"
    r"frontend|backend\s+status|api\s+health|system\s+health|"
    r"commit\s+verif|service\s+unhealthy|unhealthy\s+deployment",
    re.IGNORECASE,
)

_REPOSITORY_ANALYSIS_PATTERN = re.compile(
    r"architecture|module\s+map|code\s+structure|repository|"
    r"explain\s+(?:the\s+)?(?:jarvis\s+)?(?:code|modules)|"
    r"openclaw|websocket\s+implement|ws\s+implement",
    re.IGNORECASE,
)

_JARVIS_ARCHITECTURE_PATTERN = re.compile(
    r"\bjarvis\b.*(?:architecture|modules?|structure)|"
    r"explain\s+(?:current\s+)?jarvis|jarvis\s+architecture",
    re.IGNORECASE,
)

_GENERIC_HEALTH_TOOLS = frozenset({"inspect_health", "inspect_repository", "inspect_runtime", "read_logs"})
_ORDER_EVIDENCE_TOOLS = frozenset(
    {
        "reconcile_crypto_com_open_orders",
        "diagnose_open_orders",
        "query_database",
    }
)

PLAN_TEMPLATES: dict[InvestigationObjectiveType, list[PlanStep]] = {
    InvestigationObjectiveType.ORDER_RECONCILIATION: [
        (
            "step_1",
            "inspect_exchange_open_orders_readonly",
            "reconcile_crypto_com_open_orders",
            "Inspect exchange open orders (read-only)",
        ),
        (
            "step_2",
            "inspect_dashboard_open_orders_readonly",
            "diagnose_open_orders",
            "Inspect dashboard/database open orders (read-only)",
        ),
        (
            "step_3",
            "compare_open_orders_readonly",
            "reconcile_crypto_com_open_orders",
            "Compare exchange vs dashboard open orders (read-only)",
        ),
        (
            "step_4",
            "inspect_exchange_sync_mapping_readonly",
            "search_repository",
            "Inspect exchange_sync mapping and order sync logic (read-only)",
        ),
        (
            "step_5",
            "inspect_relevant_logs_readonly",
            "search_logs",
            "Search logs for order sync and reconciliation errors (read-only)",
        ),
        (
            "step_6",
            "produce_order_reconciliation_report",
            "diagnose_open_orders",
            "Produce order reconciliation report with evidence (read-only)",
        ),
    ],
    InvestigationObjectiveType.DEPLOYMENT_HEALTH: [
        ("step_1", "gather_logs", "read_logs", "Gather recent deployment/application logs"),
        ("step_2", "inspect_health", "inspect_health", "Inspect dashboard and API health"),
        ("step_3", "inspect_runtime", "inspect_runtime", "Inspect runtime environment flags"),
        ("step_4", "inspect_container", "inspect_container", "Inspect running containers"),
    ],
    InvestigationObjectiveType.REPOSITORY_ANALYSIS: [
        ("step_1", "inspect_repository", "inspect_repository", "Map repository modules and layout"),
        ("step_2", "search_repository", "search_repository", "Search repository for relevant code"),
        ("step_3", "summarize_modules", "inspect_runtime", "Summarize runtime configuration"),
    ],
    InvestigationObjectiveType.ALERT_INVESTIGATION: [
        ("step_1", "search_logs", "search_logs", "Search logs for alert-related errors"),
        ("step_2", "inspect_health", "inspect_health", "Verify service health endpoints"),
        ("step_3", "search_repository", "search_repository", "Locate alert handling code"),
    ],
    InvestigationObjectiveType.SIGNAL_MONITOR_INVESTIGATION: [
        ("step_1", "search_repository", "search_repository", "Locate signal/monitor modules"),
        ("step_2", "search_logs", "search_logs", "Search logs for signal events"),
        ("step_3", "inspect_health", "inspect_health", "Verify monitor health endpoints"),
    ],
    InvestigationObjectiveType.EXCHANGE_AUTH_INVESTIGATION: [
        (
            "step_1",
            "inspect_exchange_auth_readonly",
            "reconcile_crypto_com_open_orders",
            "Probe exchange auth via read-only API call",
        ),
        ("step_2", "search_logs", "search_logs", "Search logs for auth/credential errors"),
        ("step_3", "inspect_runtime", "inspect_runtime", "Inspect runtime credential flags"),
        ("step_4", "search_repository", "search_repository", "Locate credential configuration"),
    ],
    InvestigationObjectiveType.GENERIC_INVESTIGATION: [
        ("step_1", "gather_logs", "read_logs", "Gather contextual logs"),
        ("step_2", "inspect_health", "inspect_health", "Inspect system health"),
        ("step_3", "identify_root_cause", "inspect_repository", "Review repository and runtime context"),
    ],
}


def classify_investigation_objective(objective: str) -> InvestigationObjectiveType:
    """Classify user objective into an investigation type (deterministic, first match wins)."""
    raw = (objective or "").strip()
    if not raw:
        return InvestigationObjectiveType.GENERIC_INVESTIGATION

    text = _normalize_objective_text(raw)

    if _ORDER_RECONCILIATION_PATTERN.search(text) or _ORDER_RECONCILIATION_PATTERN.search(raw):
        return InvestigationObjectiveType.ORDER_RECONCILIATION
    if _ALERT_INVESTIGATION_PATTERN.search(text):
        return InvestigationObjectiveType.ALERT_INVESTIGATION
    if _EXCHANGE_AUTH_PATTERN.search(text):
        return InvestigationObjectiveType.EXCHANGE_AUTH_INVESTIGATION
    if _SIGNAL_MONITOR_PATTERN.search(text):
        return InvestigationObjectiveType.SIGNAL_MONITOR_INVESTIGATION
    if _DEPLOYMENT_HEALTH_PATTERN.search(text):
        return InvestigationObjectiveType.DEPLOYMENT_HEALTH
    if _JARVIS_ARCHITECTURE_PATTERN.search(text) or (
        _REPOSITORY_ANALYSIS_PATTERN.search(text) and "order" not in text and "exchange" not in text
    ):
        return InvestigationObjectiveType.REPOSITORY_ANALYSIS
    if _REPOSITORY_ANALYSIS_PATTERN.search(text):
        return InvestigationObjectiveType.REPOSITORY_ANALYSIS

    return InvestigationObjectiveType.GENERIC_INVESTIGATION


def get_plan_template(investigation_type: InvestigationObjectiveType) -> list[PlanStep]:
    return list(PLAN_TEMPLATES.get(investigation_type, PLAN_TEMPLATES[InvestigationObjectiveType.GENERIC_INVESTIGATION]))


def order_reconciliation_plan_actions(plan_steps: list[PlanStep]) -> list[str]:
    return [action for _, action, _, _ in plan_steps]


def _tool_output(tool_results: list[dict[str, Any]], tool_name: str) -> dict[str, Any]:
    for entry in tool_results or []:
        if str(entry.get("tool") or "").lower() == tool_name.lower():
            output = entry.get("output")
            return output if isinstance(output, dict) else {}
    return {}


def assess_order_reconciliation_evidence(tool_results: list[dict[str, Any]] | None) -> dict[str, Any]:
    """
    Evaluate required order-reconciliation evidence.

    Returns dict with booleans and missing_evidence list.
    """
    results = tool_results or []
    tools_run = {str(r.get("tool") or "").lower() for r in results}
    only_generic = tools_run and tools_run.issubset(_GENERIC_HEALTH_TOOLS)

    exchange_evidence = False
    dashboard_evidence = False
    comparison_evidence = False
    sync_evidence = False
    missing: list[str] = []

    for entry in results:
        tool = str(entry.get("tool") or "").lower()
        output = entry.get("output")
        if not isinstance(output, dict):
            if entry.get("error") and tool in _ORDER_EVIDENCE_TOOLS:
                if tool == "reconcile_crypto_com_open_orders":
                    exchange_evidence = True
                    comparison_evidence = True
                elif tool == "diagnose_open_orders":
                    dashboard_evidence = True
            continue

        if tool == "reconcile_crypto_com_open_orders":
            counts = output.get("counts")
            if isinstance(counts, dict) and counts:
                exchange_evidence = True
                dashboard_evidence = True
                comparison_evidence = True
            elif output.get("discrepancies") is not None:
                comparison_evidence = True
                exchange_evidence = True
            elif output.get("skipped") or output.get("error") or entry.get("error"):
                exchange_evidence = True
                comparison_evidence = True
            elif output.get("evidence"):
                exchange_evidence = True
                comparison_evidence = True

        elif tool == "diagnose_open_orders":
            if output.get("exchange_total_count") is not None:
                exchange_evidence = True
            if output.get("dashboard_effective_count") is not None:
                dashboard_evidence = True
            if output.get("root_cause") or output.get("conclusion") or output.get("evidence"):
                comparison_evidence = True
                if output.get("evidence"):
                    exchange_evidence = True
                    dashboard_evidence = True

        elif tool == "query_database":
            preset = str(output.get("preset") or "").lower()
            if preset == "count_open_orders" or output.get("count") is not None or output.get("query_executed"):
                dashboard_evidence = True

        elif tool == "search_repository":
            topic = str(output.get("topic") or "").lower()
            matches = output.get("matches") or []
            if "exchange_sync" in topic or "sync" in str(matches).lower() or output.get("match_count", 0) > 0:
                sync_evidence = True
            elif entry.get("ok", True):
                sync_evidence = True

        elif tool == "search_logs":
            if output.get("matches") or output.get("match_count", 0) > 0:
                sync_evidence = True
            elif entry.get("ok", True):
                sync_evidence = True

    if not exchange_evidence:
        missing.append("exchange_open_order_count_or_explicit_exchange_query_failure")
    if not dashboard_evidence:
        missing.append("dashboard_open_order_count_or_explicit_dashboard_query_failure")
    if not comparison_evidence:
        missing.append("comparison_result_or_explicit_reason_comparison_could_not_run")
    if not sync_evidence:
        missing.append("exchange_sync_mapping_evidence_or_explicit_reason_unavailable")

    sufficient = bool(exchange_evidence and dashboard_evidence and comparison_evidence and sync_evidence)
    return {
        "exchange_evidence": exchange_evidence,
        "dashboard_evidence": dashboard_evidence,
        "comparison_evidence": comparison_evidence,
        "sync_evidence": sync_evidence,
        "only_generic_tools": only_generic,
        "missing_evidence": missing,
        "sufficient": sufficient,
    }
