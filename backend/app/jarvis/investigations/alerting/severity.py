"""Deterministic severity classification for investigation findings (no LLM)."""

from __future__ import annotations

import re
from typing import Any

from app.jarvis.investigations.alerting.types import AlertInput, AlertSeverity
from app.jarvis.investigations.investigation_types import InvestigationStatus

# (compiled pattern, alert_type) — first CRITICAL match wins, then WARNING, then INFO fallback.
_CRITICAL_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"exchange.*unreachable|cannot reach exchange|exchange connectivity failed|exchange.*not reachable", re.I), "exchange_unreachable"),
    (re.compile(r"database.*unavailable|database.*down|db.*unavailable|cannot connect.*database|database connection failed", re.I), "database_unavailable"),
    (re.compile(r"open order.*inconsist|active.*mismatch|dashboard.*exchange.*mismatch|open order counts differ", re.I), "open_order_inconsistency"),
    (re.compile(r"missing production data|no production data|production data.*missing|missing.*production.*records", re.I), "missing_production_data"),
    (re.compile(r"repeated investigation fail|investigation.*failed repeatedly|scheduler.*failures", re.I), "repeated_investigation_failures"),
)

_WARNING_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"reconciliation.*mismatch|portfolio.*mismatch|wallet.*mismatch", re.I), "reconciliation_mismatch"),
    (re.compile(r"api.*degrad|degraded.*api|high.*latency|slow.*response", re.I), "api_degradation"),
    (re.compile(r"transient.*fail|intermittent.*fail|retry.*exhausted|temporary.*error", re.I), "transient_failures"),
    (re.compile(r"websocket.*unstable|websocket.*stale|websocket.*disconnect|prices.*stale", re.I), "websocket_instability"),
    (re.compile(r"trigger.*50001|partial.*fail|collector.*fail|insufficient evidence", re.I), "partial_investigation_failure"),
    (re.compile(r"deployment.*unhealthy|health check.*fail", re.I), "deployment_degraded"),
)

_INFO_ALERT_TYPE = "investigation_completed"


def _normalize_text(*parts: str | None) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip()).lower()


def _collect_text_blobs(report: Any) -> str:
    parts: list[str] = [
        str(getattr(report, "objective", "") or ""),
        str(getattr(report, "summary", "") or ""),
        str(getattr(report, "root_cause", "") or ""),
        str(getattr(report, "impact", "") or ""),
        str(getattr(report, "next_action", "") or ""),
        str(getattr(report, "category", "") or ""),
        str(getattr(report, "template_id", "") or ""),
        str(getattr(report, "resolution_status", "") or ""),
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


def _status_severity(report: Any) -> tuple[AlertSeverity, str] | None:
    status = getattr(report, "status", None)
    status_val = status.value if hasattr(status, "value") else str(status or "")
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
    if cat == "orders" and re.search(r"mismatch|inconsist|differ", text):
        return AlertSeverity.CRITICAL, "open_order_inconsistency"
    if cat == "websocket" and re.search(r"stale|disconnect|unstable|error", text):
        return AlertSeverity.WARNING, "websocket_instability"
    if cat == "portfolio" and re.search(r"mismatch|reconcil", text):
        return AlertSeverity.WARNING, "reconciliation_mismatch"
    return None


def _is_clean_completion(report: Any, text: str) -> bool:
    status = getattr(report, "status", None)
    status_val = status.value if hasattr(status, "value") else str(status or "")
    if status_val != InvestigationStatus.COMPLETED.value:
        return False
    clean_markers = (
        "no active dashboard/exchange mismatch",
        "all checks passed",
        "no issues detected",
        "healthy",
        "no mismatch detected",
    )
    if any(m in text for m in clean_markers):
        return True
    root = (getattr(report, "root_cause", None) or "").lower()
    if not root or root in {"none", "n/a", "not determined", "unknown"}:
        return True
    return False


def classify_investigation_report(
    report: Any,
    *,
    source: str,
) -> AlertInput | None:
    """
    Classify a completed investigation into an alert input.

    Returns None when alerting should be skipped entirely (disabled path handled upstream).
    """
    text = _collect_text_blobs(report)
    category = str(getattr(report, "category", "") or "")
    investigation_id = str(getattr(report, "investigation_id", "") or "") or None

    status_result = _status_severity(report)
    if status_result:
        severity, alert_type = status_result
        title = f"Investigation {alert_type.replace('_', ' ')}"
        summary = (getattr(report, "summary", None) or getattr(report, "root_cause", None) or alert_type)[:2000]
        return AlertInput(
            alert_type=alert_type,
            source=source,
            title=title,
            summary=summary,
            severity=severity,
            investigation_id=investigation_id,
            evidence=list(getattr(report, "evidence", None) or []),
            normalized_finding=_normalize_text(alert_type, source, summary),
        )

    cat_result = _category_boost(text, category)
    if cat_result:
        severity, alert_type = cat_result
        title = alert_type.replace("_", " ").title()
        summary = (getattr(report, "summary", None) or getattr(report, "root_cause", None) or title)[:2000]
        return AlertInput(
            alert_type=alert_type,
            source=source,
            title=title,
            summary=summary,
            severity=severity,
            investigation_id=investigation_id,
            evidence=list(getattr(report, "evidence", None) or []),
            normalized_finding=_normalize_text(alert_type, source, summary),
        )

    critical_type = _match_rules(text, _CRITICAL_RULES)
    if critical_type:
        title = critical_type.replace("_", " ").title()
        summary = (getattr(report, "summary", None) or getattr(report, "root_cause", None) or title)[:2000]
        return AlertInput(
            alert_type=critical_type,
            source=source,
            title=title,
            summary=summary,
            severity=AlertSeverity.CRITICAL,
            investigation_id=investigation_id,
            evidence=list(getattr(report, "evidence", None) or []),
            normalized_finding=_normalize_text(critical_type, source, summary),
        )

    warning_type = _match_rules(text, _WARNING_RULES)
    if warning_type:
        title = warning_type.replace("_", " ").title()
        summary = (getattr(report, "summary", None) or getattr(report, "root_cause", None) or title)[:2000]
        return AlertInput(
            alert_type=warning_type,
            source=source,
            title=title,
            summary=summary,
            severity=AlertSeverity.WARNING,
            investigation_id=investigation_id,
            evidence=list(getattr(report, "evidence", None) or []),
            normalized_finding=_normalize_text(warning_type, source, summary),
        )

    if _is_clean_completion(report, text):
        summary = (getattr(report, "summary", None) or "Investigation completed successfully")[:2000]
        return AlertInput(
            alert_type=_INFO_ALERT_TYPE,
            source=source,
            title="Investigation completed successfully",
            summary=summary,
            severity=AlertSeverity.INFO,
            investigation_id=investigation_id,
            evidence=list(getattr(report, "evidence", None) or []),
            normalized_finding=_normalize_text(_INFO_ALERT_TYPE, source, summary),
        )

    # Completed with findings but no rule match — treat as WARNING for visibility.
    status = getattr(report, "status", None)
    status_val = status.value if hasattr(status, "value") else str(status or "")
    if status_val == InvestigationStatus.COMPLETED.value and (getattr(report, "root_cause", None) or getattr(report, "impact", None)):
        summary = (getattr(report, "summary", None) or getattr(report, "root_cause", None) or "Investigation finding")[:2000]
        return AlertInput(
            alert_type="investigation_finding",
            source=source,
            title="Investigation finding requires attention",
            summary=summary,
            severity=AlertSeverity.WARNING,
            investigation_id=investigation_id,
            evidence=list(getattr(report, "evidence", None) or []),
            normalized_finding=_normalize_text("investigation_finding", source, summary),
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
