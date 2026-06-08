"""Read-only metric resolver for Jarvis key results (no execution)."""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

Confidence = Literal["high", "medium", "low"]

SUPPORTED_METRICS = frozenset({
    "aws_monthly_spend",
    "aws_daily_spend",
    "aws_ec2_count",
    "aws_unattached_ebs_count",
    "aws_unused_eip_count",
    "aws_open_security_groups",
    "aws_critical_findings",
    "crypto_portfolio_difference_pct",
    "crypto_portfolio_difference_usd",
    "crypto_reconciliation_accuracy_pct",
    "crypto_critical_findings",
    "jarvis_open_followups",
    "jarvis_critical_followups",
    "jarvis_open_action_plans",
    "jarvis_blocked_initiatives",
    "jarvis_overdue_initiatives",
})

# Backward-compatible aliases from seed data and earlier phases.
METRIC_ALIASES: dict[str, str] = {
    "unattached_ebs": "aws_unattached_ebs_count",
    "unused_eip": "aws_unused_eip_count",
    "portfolio_accuracy_pct": "crypto_reconciliation_accuracy_pct",
    "portfolio_difference_pct": "crypto_portfolio_difference_pct",
    "sg_exposed_0_0_0_0": "aws_open_security_groups",
    "critical_findings": "_combined_critical_findings",
}


def _result(
    *,
    metric_name: str,
    current_value: float,
    source: str,
    confidence: Confidence = "high",
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "metric_name": metric_name,
        "current_value": round(float(current_value), 4),
        "source": source,
        "confidence": confidence,
        "error": error,
    }


def _error_result(metric_name: str, message: str) -> dict[str, Any]:
    return _result(
        metric_name=metric_name,
        current_value=0.0,
        source="unavailable",
        confidence="low",
        error=message,
    )


def _count_audit_critical(findings_groups: list[list[dict[str, Any]]]) -> int:
    count = 0
    for group in findings_groups:
        for item in group:
            sev = str(item.get("severity") or "").lower()
            if sev in ("critical", "high"):
                count += 1
    return count


def _resolve_aws_critical_findings() -> dict[str, Any]:
    from app.jarvis.mvp.audit_persistence import get_audit_run, list_audit_runs

    audits = list_audit_runs(limit=1)
    if not audits:
        return _result(
            metric_name="aws_critical_findings",
            current_value=0,
            source="AWS Audit (no runs)",
            confidence="low",
        )

    detail = get_audit_run(audits[0]["audit_id"]) or {}
    groups = [
        detail.get("cost_findings") or [],
        detail.get("security_findings") or [],
        detail.get("resource_findings") or [],
    ]
    count = _count_audit_critical(groups)
    return _result(
        metric_name="aws_critical_findings",
        current_value=count,
        source=f"AWS Audit ({audits[0]['audit_id'][:8]}…)",
        confidence="high" if detail else "medium",
    )


def _resolve_crypto_critical_findings() -> dict[str, Any]:
    from app.jarvis.mvp.crypto_audit_persistence import get_crypto_audit_run, get_latest_crypto_audit_run

    latest = get_latest_crypto_audit_run()
    if not latest:
        return _result(
            metric_name="crypto_critical_findings",
            current_value=0,
            source="Crypto Audit (no runs)",
            confidence="low",
        )

    detail = get_crypto_audit_run(latest["audit_id"]) or latest
    groups = [
        detail.get("wallet_findings") or [],
        detail.get("position_findings") or [],
        detail.get("valuation_findings") or [],
        detail.get("price_feed_findings") or [],
    ]
    count = _count_audit_critical(groups)
    return _result(
        metric_name="crypto_critical_findings",
        current_value=count,
        source=f"Crypto Audit ({latest['audit_id'][:8]}…)",
        confidence="high",
    )


def _resolve_combined_critical_findings() -> dict[str, Any]:
    aws = _resolve_aws_critical_findings()
    crypto = _resolve_crypto_critical_findings()
    if aws.get("error") and crypto.get("error"):
        return _error_result("critical_findings", "No AWS or crypto audit data available")

    total = float(aws.get("current_value") or 0) + float(crypto.get("current_value") or 0)
    confidence: Confidence = "high"
    if aws.get("confidence") == "low" or crypto.get("confidence") == "low":
        confidence = "medium"
    return _result(
        metric_name="critical_findings",
        current_value=total,
        source="AWS Audit + Crypto Audit",
        confidence=confidence,
    )


def resolve_metric(metric_name: str) -> dict[str, Any]:
    """
    Resolve a read-only metric value for KR auto-refresh.

    Returns dict with metric_name, current_value, source, confidence, error.
    """
    raw = (metric_name or "").strip()
    if not raw:
        return _error_result("unknown", "metric_name is required")

    canonical = METRIC_ALIASES.get(raw, raw)

    try:
        if canonical == "_combined_critical_findings":
            return _resolve_combined_critical_findings()

        if canonical == "aws_monthly_spend":
            from app.jarvis.mvp.metrics_persistence import _fetch_aws_monthly_cost

            value = _fetch_aws_monthly_cost()
            return _result(
                metric_name=raw,
                current_value=value,
                source="AWS Cost Explorer (30d)",
                confidence="high" if value > 0 else "medium",
            )

        if canonical == "aws_daily_spend":
            from app.jarvis.mvp.metrics_persistence import _fetch_aws_daily_cost

            value = _fetch_aws_daily_cost()
            return _result(
                metric_name=raw,
                current_value=value,
                source="AWS Cost Explorer (24h)",
                confidence="high" if value > 0 else "medium",
            )

        if canonical == "aws_ec2_count":
            from app.jarvis.mvp.aws_auditor_tools import get_ec2_inventory

            inv = get_ec2_inventory()
            if not inv.get("success"):
                return _error_result(raw, inv.get("error") or "EC2 inventory unavailable")
            return _result(
                metric_name=raw,
                current_value=float(inv.get("total") or 0),
                source="AWS EC2 API",
            )

        if canonical == "aws_unattached_ebs_count":
            from app.jarvis.mvp.aws_auditor_tools import get_ebs_inventory

            inv = get_ebs_inventory()
            if not inv.get("success"):
                return _error_result(raw, inv.get("error") or "EBS inventory unavailable")
            return _result(
                metric_name=raw,
                current_value=float(inv.get("unattached_count") or 0),
                source="AWS EBS API",
            )

        if canonical == "aws_unused_eip_count":
            from app.jarvis.mvp.aws_auditor_tools import get_eip_inventory

            inv = get_eip_inventory()
            if not inv.get("success"):
                return _error_result(raw, inv.get("error") or "EIP inventory unavailable")
            return _result(
                metric_name=raw,
                current_value=float(inv.get("unattached_count") or 0),
                source="AWS EC2 EIP API",
            )

        if canonical == "aws_open_security_groups":
            from app.jarvis.mvp.aws_auditor_tools import get_security_group_inventory

            inv = get_security_group_inventory()
            if not inv.get("success"):
                return _error_result(raw, inv.get("error") or "Security group inventory unavailable")
            return _result(
                metric_name=raw,
                current_value=float(inv.get("risky_count") or 0),
                source="AWS EC2 Security Groups",
            )

        if canonical == "aws_critical_findings":
            resolved = _resolve_aws_critical_findings()
            resolved["metric_name"] = raw
            return resolved

        if canonical == "crypto_portfolio_difference_pct":
            from app.jarvis.mvp.metrics_persistence import _fetch_crypto_health

            crypto = _fetch_crypto_health()
            return _result(
                metric_name=raw,
                current_value=float(crypto.get("portfolio_difference_pct") or 0),
                source="Crypto Audit / live reconciliation",
                confidence="high" if crypto.get("last_reconciliation_date") else "medium",
            )

        if canonical == "crypto_portfolio_difference_usd":
            from app.jarvis.mvp.metrics_persistence import _fetch_crypto_health

            crypto = _fetch_crypto_health()
            dash = float(crypto.get("dashboard_portfolio_value") or 0)
            ex = float(crypto.get("exchange_portfolio_value") or 0)
            return _result(
                metric_name=raw,
                current_value=round(abs(ex - dash), 2),
                source="Crypto Audit / live reconciliation",
                confidence="high" if crypto.get("last_reconciliation_date") else "medium",
            )

        if canonical == "crypto_reconciliation_accuracy_pct":
            from app.jarvis.mvp.metrics_persistence import _fetch_crypto_health

            crypto = _fetch_crypto_health()
            diff_pct = float(crypto.get("portfolio_difference_pct") or 0)
            accuracy = max(0.0, min(100.0, 100.0 - diff_pct))
            return _result(
                metric_name=raw,
                current_value=round(accuracy, 2),
                source="Crypto Audit / live reconciliation",
                confidence="high" if crypto.get("last_reconciliation_date") else "medium",
            )

        if canonical == "crypto_critical_findings":
            resolved = _resolve_crypto_critical_findings()
            resolved["metric_name"] = raw
            return resolved

        if canonical == "jarvis_open_followups":
            from app.jarvis.mvp.followup_persistence import get_followup_summary

            summary = get_followup_summary()
            return _result(
                metric_name=raw,
                current_value=float(summary.get("open_followups") or 0),
                source="Jarvis Follow-ups",
            )

        if canonical == "jarvis_critical_followups":
            from app.jarvis.mvp.followup_persistence import get_followup_summary

            summary = get_followup_summary()
            return _result(
                metric_name=raw,
                current_value=float(summary.get("critical_followups") or 0),
                source="Jarvis Follow-ups",
            )

        if canonical == "jarvis_open_action_plans":
            from app.jarvis.mvp.action_plan_persistence import list_action_plans

            plans = list_action_plans(limit=100)
            open_count = sum(1 for p in plans if str(p.get("status")) == "proposed")
            return _result(
                metric_name=raw,
                current_value=float(open_count),
                source="Jarvis Action Plans",
            )

        if canonical == "jarvis_blocked_initiatives":
            from app.jarvis.mvp.initiative_persistence import list_all_initiatives

            items = list_all_initiatives()
            blocked = sum(1 for i in items if str(i.get("status")) == "blocked")
            return _result(
                metric_name=raw,
                current_value=float(blocked),
                source="Jarvis Initiatives",
            )

        if canonical == "jarvis_overdue_initiatives":
            from app.jarvis.mvp.initiative_persistence import is_initiative_overdue, list_all_initiatives

            items = list_all_initiatives()
            overdue = sum(1 for i in items if is_initiative_overdue(i))
            return _result(
                metric_name=raw,
                current_value=float(overdue),
                source="Jarvis Initiatives",
            )

        return _error_result(raw, f"Unsupported metric_name: {raw}")

    except Exception as exc:
        logger.warning("resolve_metric failed metric=%s err=%s", raw, exc)
        return _error_result(raw, str(exc))
