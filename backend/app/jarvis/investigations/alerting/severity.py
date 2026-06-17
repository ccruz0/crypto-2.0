"""Deterministic severity classification for investigation findings (no LLM)."""

from __future__ import annotations

import re
from typing import Any

from app.jarvis.investigations.alerting.types import AlertInput, AlertSeverity
from app.jarvis.investigations.investigation_types import InvestigationStatus

_RESOLVED_MISMATCH_CAUSE = "no active dashboard/exchange mismatch detected"

# Authoritative conclusion markers — final investigation outcome only.
_RESOLVED_HEALTHY_MARKERS = (
    _RESOLVED_MISMATCH_CAUSE,
    "all checks passed",
    "no issues detected",
    "healthy",
    "no mismatch detected",
)

# Patterns applied only to authoritative text (summary, root_cause, resolution_status, etc.).
# Negated mismatch phrases must not match (e.g. "no active dashboard/exchange mismatch").
_TRUE_MISMATCH_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?<!no active )(?<!no )dashboard.{0,40}exchange.{0,40}mismatch(?! detected)",
            re.I,
        ),
        "open_order_inconsistency",
    ),
    (
        re.compile(
            r"active.{0,20}dashboard/exchange.{0,20}mismatch detected",
            re.I,
        ),
        "open_order_inconsistency",
    ),
    (
        re.compile(
            r"open order counts differ|open order.{0,30}inconsist",
            re.I,
        ),
        "open_order_inconsistency",
    ),
)

_CRITICAL_INFRA_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"exchange.*unreachable|exchange.*unavailable|cannot reach exchange"
            r"|exchange connectivity failed|exchange.*not reachable"
            r"|exchange authentication fail",
            re.I,
        ),
        "exchange_unreachable",
    ),
    (
        re.compile(
            r"database.*unavailable|database.*down|db.*unavailable"
            r"|cannot connect.*database|database connection failed",
            re.I,
        ),
        "database_unavailable",
    ),
)

_WARNING_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"reconciliation.*mismatch|portfolio.*mismatch|wallet.*mismatch", re.I), "reconciliation_mismatch"),
    (re.compile(r"api.*degrad|degraded.*api|high.*latency|slow.*response", re.I), "api_degradation"),
    (re.compile(r"transient.*fail|intermittent.*fail|retry.*exhausted|temporary.*error", re.I), "transient_failures"),
    (re.compile(r"websocket.*unstable|websocket.*stale|websocket.*disconnect|prices.*stale", re.I), "websocket_instability"),
    (re.compile(r"trigger.*50001|partial.*fail|collector.*fail|insufficient evidence", re.I), "partial_investigation_failure"),
    (re.compile(r"deployment.*unhealthy|health check.*fail", re.I), "deployment_degraded"),
    (
        re.compile(r"missing production data|no production data|production data.*missing|missing.*production.*records", re.I),
        "missing_production_data",
    ),
    (re.compile(r"repeated investigation fail|investigation.*failed repeatedly|scheduler.*failures", re.I), "repeated_investigation_failures"),
)

_INFO_ALERT_TYPE = "investigation_completed"


def _normalize_text(*parts: str | None) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip()).lower()


def _collect_authoritative_text(report: Any) -> str:
    """Final investigation conclusions — used for severity decisions."""
    parts: list[str] = [
        str(getattr(report, "objective", "") or ""),
        str(getattr(report, "summary", "") or ""),
        str(getattr(report, "root_cause", "") or ""),
        str(getattr(report, "impact", "") or ""),
        str(getattr(report, "next_action", "") or ""),
        str(getattr(report, "resolution_status", "") or ""),
    ]
    return _normalize_text(*parts)


def _collect_diagnostic_text(report: Any) -> str:
    """Intermediate evidence and collector output — not used for severity escalation."""
    parts: list[str] = [
        str(getattr(report, "category", "") or ""),
        str(getattr(report, "template_id", "") or ""),
    ]
    for failure in getattr(report, "collector_failures", None) or []:
        parts.append(str(failure))
    for item in getattr(report, "evidence", None) or []:
        if isinstance(item, dict):
            parts.append(str(item.get("detail") or ""))
            parts.append(str(item.get("reference") or ""))
    return _normalize_text(*parts)


def _match_rules(text: str, rules: tuple[tuple[re.Pattern[str], str], ...]) -> str | None:
    for pattern, alert_type in rules:
        if pattern.search(text):
            return alert_type
    return None


def _status_value(report: Any) -> str:
    status = getattr(report, "status", None)
    return status.value if hasattr(status, "value") else str(status or "")


def _is_active_open_order_mismatch(report: Any) -> bool:
    """Investigation concluded with an active dashboard/exchange count mismatch."""
    resolution = (getattr(report, "resolution_status", None) or "").lower()
    if resolution == "active":
        return True
    root = (getattr(report, "root_cause", None) or "").lower()
    if "active dashboard/exchange open-order mismatch" in root:
        return True
    return _match_rules(_collect_authoritative_text(report), _TRUE_MISMATCH_RULES) is not None


def _is_resolved_healthy(report: Any) -> bool:
    resolution = (getattr(report, "resolution_status", None) or "").lower()
    if resolution == "resolved":
        return True

    root = (getattr(report, "root_cause", None) or "").lower()
    if root == _RESOLVED_MISMATCH_CAUSE:
        return True

    authoritative = _collect_authoritative_text(report)
    if any(marker in authoritative for marker in _RESOLVED_HEALTHY_MARKERS):
        return True

    if _status_value(report) != InvestigationStatus.COMPLETED.value:
        return False

    if not root or root in {"none", "n/a", "not determined", "unknown"}:
        return True

    return False


def _status_severity(report: Any) -> tuple[AlertSeverity, str] | None:
    status_val = _status_value(report)
    if status_val == InvestigationStatus.FAILED.value:
        return AlertSeverity.CRITICAL, "investigation_failed"
    if status_val in {InvestigationStatus.PARTIAL_FAILURE.value, InvestigationStatus.INSUFFICIENT_EVIDENCE.value}:
        return AlertSeverity.WARNING, "investigation_partial_failure"
    return None


def _category_boost(text: str, category: str) -> tuple[AlertSeverity, str] | None:
    cat = (category or "").lower()
    if cat == "exchange" and re.search(r"unreachable|unavailable|cannot|failed|error", text):
        return AlertSeverity.CRITICAL, "exchange_unreachable"
    if cat == "database" and re.search(r"unavailable|error|failed|cannot|down", text):
        return AlertSeverity.CRITICAL, "database_unavailable"
    if cat == "orders" and _match_rules(text, _TRUE_MISMATCH_RULES):
        return AlertSeverity.CRITICAL, "open_order_inconsistency"
    if cat == "websocket" and re.search(r"stale|disconnect|unstable|error", text):
        return AlertSeverity.WARNING, "websocket_instability"
    if cat == "portfolio" and re.search(r"mismatch|reconcil", text):
        return AlertSeverity.WARNING, "reconciliation_mismatch"
    return None


def _build_alert_input(
    *,
    alert_type: str,
    source: str,
    title: str,
    summary: str,
    severity: AlertSeverity,
    report: Any,
) -> AlertInput:
    investigation_id = str(getattr(report, "investigation_id", "") or "") or None
    return AlertInput(
        alert_type=alert_type,
        source=source,
        title=title,
        summary=summary[:2000],
        severity=severity,
        investigation_id=investigation_id,
        evidence=list(getattr(report, "evidence", None) or []),
        normalized_finding=_normalize_text(alert_type, source, summary),
    )


def classify_investigation_report(
    report: Any,
    *,
    source: str,
) -> AlertInput | None:
    """
    Classify a completed investigation into an alert input.

    Decision tree (first match wins):
    1. FAILED status → CRITICAL
    2. PARTIAL_FAILURE / INSUFFICIENT_EVIDENCE → WARNING
    3. Resolved healthy (resolution_status=resolved or authoritative conclusion) → INFO
    4. Active open-order mismatch (resolution_status=active or authoritative mismatch) → CRITICAL
    5. Category boost on authoritative text → severity per category rules
    6. Infrastructure outage patterns on authoritative text → CRITICAL
    7. Other WARNING patterns on authoritative text → WARNING
    8. COMPLETED with root_cause/impact findings → WARNING
    9. Otherwise → None (suppressed)

    Intermediate diagnostic/evidence text never overrides steps 3–4.
    """
    authoritative = _collect_authoritative_text(report)
    category = str(getattr(report, "category", "") or "")

    status_result = _status_severity(report)
    if status_result:
        severity, alert_type = status_result
        title = f"Investigation {alert_type.replace('_', ' ')}"
        summary = getattr(report, "summary", None) or getattr(report, "root_cause", None) or alert_type
        return _build_alert_input(
            alert_type=alert_type,
            source=source,
            title=title,
            summary=str(summary),
            severity=severity,
            report=report,
        )

    if _is_resolved_healthy(report):
        summary = getattr(report, "summary", None) or "Investigation completed successfully"
        return _build_alert_input(
            alert_type=_INFO_ALERT_TYPE,
            source=source,
            title="Investigation completed successfully",
            summary=str(summary),
            severity=AlertSeverity.INFO,
            report=report,
        )

    if _is_active_open_order_mismatch(report):
        alert_type = _match_rules(authoritative, _TRUE_MISMATCH_RULES) or "open_order_inconsistency"
        title = alert_type.replace("_", " ").title()
        summary = getattr(report, "summary", None) or getattr(report, "root_cause", None) or title
        return _build_alert_input(
            alert_type=alert_type,
            source=source,
            title=title,
            summary=str(summary),
            severity=AlertSeverity.CRITICAL,
            report=report,
        )

    cat_result = _category_boost(authoritative, category)
    if cat_result:
        severity, alert_type = cat_result
        title = alert_type.replace("_", " ").title()
        summary = getattr(report, "summary", None) or getattr(report, "root_cause", None) or title
        return _build_alert_input(
            alert_type=alert_type,
            source=source,
            title=title,
            summary=str(summary),
            severity=severity,
            report=report,
        )

    critical_infra_type = _match_rules(authoritative, _CRITICAL_INFRA_RULES)
    if critical_infra_type:
        title = critical_infra_type.replace("_", " ").title()
        summary = getattr(report, "summary", None) or getattr(report, "root_cause", None) or title
        return _build_alert_input(
            alert_type=critical_infra_type,
            source=source,
            title=title,
            summary=str(summary),
            severity=AlertSeverity.CRITICAL,
            report=report,
        )

    warning_type = _match_rules(authoritative, _WARNING_RULES)
    if warning_type:
        title = warning_type.replace("_", " ").title()
        summary = getattr(report, "summary", None) or getattr(report, "root_cause", None) or title
        return _build_alert_input(
            alert_type=warning_type,
            source=source,
            title=title,
            summary=str(summary),
            severity=AlertSeverity.WARNING,
            report=report,
        )

    if _status_value(report) == InvestigationStatus.COMPLETED.value and (
        getattr(report, "root_cause", None) or getattr(report, "impact", None)
    ):
        summary = getattr(report, "summary", None) or getattr(report, "root_cause", None) or "Investigation finding"
        return _build_alert_input(
            alert_type="investigation_finding",
            source=source,
            title="Investigation finding requires attention",
            summary=str(summary),
            severity=AlertSeverity.WARNING,
            report=report,
        )

    return None


def classify_task_failure(
    *,
    source: str,
    objective: str,
    error_message: str,
    investigation_id: str | None = None,
) -> AlertInput:
    """Classify a scheduler task failure as a CRITICAL alert."""
    summary = (error_message or objective or "Scheduled investigation failed")[:2000]
    return AlertInput(
        alert_type="investigation_failed",
        source=source,
        title="Scheduled investigation failed",
        summary=summary,
        severity=AlertSeverity.CRITICAL,
        investigation_id=investigation_id,
        evidence=[],
        normalized_finding=_normalize_text("investigation_failed", source, summary),
    )
