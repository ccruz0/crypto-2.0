"""Chief of Staff Agent — prioritizes findings, audits, and action plans.

Read-only analysis only. No autonomous execution, AWS writes, trades, or
infrastructure changes. Answers: "What should Carlos focus on first?"
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from app.jarvis.mvp.action_plan_persistence import list_action_plans
from app.jarvis.mvp.audit_persistence import get_audit_run, list_audit_runs
from app.jarvis.mvp.crypto_audit_persistence import get_crypto_audit_run, list_crypto_audit_runs
from app.jarvis.mvp.decision_analytics import (
    apply_decision_adjustments,
    generate_lessons_learned,
    get_decision_analytics,
    get_decision_history_index,
)
from app.jarvis.mvp.followup_persistence import get_followup_review, list_open_followups
from app.jarvis.mvp.objective_persistence import get_strategic_alignment, record_objective_metric_snapshot
from app.jarvis.mvp.objective_persistence import list_all_objectives as list_all_strategic_objectives
from app.jarvis.mvp.initiative_persistence import (
    get_execution_review,
    get_execution_status,
    list_all_initiatives,
)
from app.jarvis.mvp.metrics_persistence import collect_daily_metrics

SourceKind = Literal[
    "aws_cost",
    "aws_security",
    "aws_resource",
    "crypto_wallet",
    "crypto_position",
    "crypto_valuation",
    "crypto_price_feed",
    "action_plan",
]

_SEVERITY_IMPACT = {"critical": 9, "high": 7, "medium": 5, "low": 2}
_SEVERITY_RISK = {"critical": 10, "high": 8, "medium": 5, "low": 2}

_CATEGORY_EFFORT: dict[str, int] = {
    "security_groups": 2,
    "ebs": 3,
    "snapshots": 4,
    "eip": 2,
    "ec2": 4,
    "tagging": 5,
    "missing_asset": 3,
    "balance_mismatch": 4,
    "valuation_mismatch": 3,
    "stale_cache": 2,
    "stale_price_feed": 3,
    "missing_position": 5,
    "duplicate_position": 5,
    "orphan_trade": 5,
}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _scores_for_finding(
    *,
    severity: str,
    category: str,
    savings_usd: float = 0.0,
) -> tuple[int, int, int]:
    sev = str(severity or "medium").lower()
    impact = _SEVERITY_IMPACT.get(sev, 5)
    risk = _SEVERITY_RISK.get(sev, 5)
    effort = _CATEGORY_EFFORT.get(str(category or "").lower(), 5)

    if savings_usd >= 50:
        impact = min(10, impact + 2)
    elif savings_usd >= 10:
        impact = min(10, impact + 1)

    return impact, risk, effort


def _priority_score(impact: int, risk: int, effort: int) -> float:
    safe_effort = max(effort, 1)
    return round((impact * risk) / safe_effort, 2)


def _priority_item(
    *,
    title: str,
    reason: str,
    expected_impact: str,
    estimated_savings_usd: float,
    risk_if_ignored: str,
    impact: int,
    risk: int,
    effort: int,
    source_kind: SourceKind,
    source_id: str | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "reason": reason,
        "expected_impact": expected_impact,
        "estimated_savings_usd": round(estimated_savings_usd, 2),
        "risk_if_ignored": risk_if_ignored,
        "impact": impact,
        "risk": risk,
        "effort": effort,
        "priority_score": _priority_score(impact, risk, effort),
        "source_kind": source_kind,
        "source_id": source_id,
    }


def _aws_finding_items(audit: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    audit_id = audit.get("audit_id")

    for finding in audit.get("cost_findings") or []:
        category = str(finding.get("category") or "cost").lower()
        savings = float(finding.get("estimated_monthly_savings_usd") or 0)
        impact, risk, effort = _scores_for_finding(
            severity=str(finding.get("severity") or "medium"),
            category=category,
            savings_usd=savings,
        )
        title_map = {
            "ebs": "Remove unattached EBS volumes",
            "snapshots": "Archive or delete stale EBS snapshots",
            "eip": "Release unattached Elastic IPs",
        }
        items.append(
            _priority_item(
                title=title_map.get(category, "Review AWS cost finding"),
                reason=str(finding.get("finding") or "Cost optimization opportunity"),
                expected_impact=f"Estimated ${savings:,.2f}/mo savings",
                estimated_savings_usd=savings,
                risk_if_ignored="Continued unnecessary AWS spend",
                impact=impact,
                risk=risk,
                effort=effort,
                source_kind="aws_cost",
                source_id=audit_id,
            )
        )

    for finding in audit.get("security_findings") or []:
        category = str(finding.get("category") or "security").lower()
        impact, risk, effort = _scores_for_finding(
            severity=str(finding.get("severity") or "high"),
            category=category,
        )
        count = int(finding.get("count") or 0)
        items.append(
            _priority_item(
                title="Restrict open security group ingress" if category == "security_groups" else "Address AWS security finding",
                reason=str(finding.get("finding") or "Security exposure detected"),
                expected_impact=f"Reduces attack surface for {count} resource(s)" if count else "Improves security posture",
                estimated_savings_usd=0.0,
                risk_if_ignored="Increased risk of unauthorized access or data breach",
                impact=impact,
                risk=risk,
                effort=effort,
                source_kind="aws_security",
                source_id=audit_id,
            )
        )

    for finding in audit.get("resource_findings") or []:
        category = str(finding.get("category") or "resource").lower()
        impact, risk, effort = _scores_for_finding(
            severity=str(finding.get("severity") or "low"),
            category=category,
        )
        count = int(finding.get("count") or 0)
        title = "Apply missing resource tags" if category == "tagging" else "Review AWS resource finding"
        items.append(
            _priority_item(
                title=title,
                reason=str(finding.get("finding") or "Resource hygiene issue"),
                expected_impact=f"Improves governance for {count} resource(s)" if count else "Improves resource hygiene",
                estimated_savings_usd=0.0,
                risk_if_ignored="Poor cost allocation and operational visibility",
                impact=impact,
                risk=risk,
                effort=effort,
                source_kind="aws_resource",
                source_id=audit_id,
            )
        )

    return items


def _crypto_finding_items(audit: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    audit_id = audit.get("audit_id")
    kind_map = {
        "wallet_findings": "crypto_wallet",
        "position_findings": "crypto_position",
        "valuation_findings": "crypto_valuation",
        "price_feed_findings": "crypto_price_feed",
    }
    title_map = {
        "missing_asset": "Verify exchange sync for missing asset",
        "balance_mismatch": "Resolve portfolio balance mismatch",
        "valuation_mismatch": "Validate valuation and price feed",
        "stale_cache": "Refresh stale portfolio cache",
        "stale_price_feed": "Investigate stale price feed",
        "missing_position": "Review missing position",
        "duplicate_position": "Review duplicate position",
        "orphan_trade": "Review orphan trade",
    }

    for group_key, source_kind in kind_map.items():
        for finding in audit.get(group_key) or []:
            ftype = str(finding.get("type") or "").lower()
            impact, risk, effort = _scores_for_finding(
                severity=str(finding.get("severity") or "medium"),
                category=ftype or group_key,
            )
            diff_pct = float(audit.get("portfolio_difference_pct") or 0)
            if ftype == "balance_mismatch" and diff_pct >= 5:
                impact = min(10, impact + 1)
                risk = min(10, risk + 1)
            items.append(
                _priority_item(
                    title=title_map.get(ftype, "Review crypto audit finding"),
                    reason=str(finding.get("finding") or ftype or "Crypto finding"),
                    expected_impact="Restores portfolio reconciliation accuracy",
                    estimated_savings_usd=0.0,
                    risk_if_ignored="Portfolio decisions based on inaccurate data",
                    impact=impact,
                    risk=risk,
                    effort=effort,
                    source_kind=source_kind,  # type: ignore[arg-type]
                    source_id=audit_id,
                )
            )

    return items


def _action_plan_items(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for plan in plans:
        if str(plan.get("status") or "proposed") != "proposed":
            continue
        severity = str(plan.get("severity") or "medium").lower()
        savings = float(plan.get("estimated_savings_usd") or 0)
        impact, risk, effort = _scores_for_finding(severity=severity, category="action_plan", savings_usd=savings)
        effort = 4 if severity in ("critical", "high") else 5
        items.append(
            _priority_item(
                title=f"Review proposed action plan ({plan.get('source_type') or 'audit'})",
                reason=f"Open action plan with {severity} severity awaiting human review",
                expected_impact=plan.get("estimated_risk_reduction") or "Addresses audit findings via manual steps",
                estimated_savings_usd=savings,
                risk_if_ignored="Unresolved audit findings remain open",
                impact=impact,
                risk=risk,
                effort=effort,
                source_kind="action_plan",
                source_id=plan.get("plan_id"),
            )
        )
    return items


def _public_item(item: dict[str, Any], priority: int | None = None) -> dict[str, Any]:
    out = {
        "title": item["title"],
        "reason": item["reason"],
        "expected_impact": item["expected_impact"],
        "estimated_savings_usd": item["estimated_savings_usd"],
        "risk_if_ignored": item["risk_if_ignored"],
    }
    if priority is not None:
        out["priority"] = priority
    if item.get("decision_context"):
        out["decision_context"] = item["decision_context"]
    return out


def calculate_health_score(
    *,
    scored_items: list[dict[str, Any]],
    metrics: dict[str, Any],
    aws_audit_age_days: int | None,
    crypto_audit_age_days: int | None,
    proposed_plan_count: int,
) -> int:
    """Compute overall health score 0-100 from findings and platform state."""
    score = 100.0

    for item in scored_items:
        impact = int(item.get("impact") or 0)
        risk = int(item.get("risk") or 0)
        if impact >= 9 or risk >= 9:
            score -= 8
        elif impact >= 7 or risk >= 7:
            score -= 4
        elif impact >= 5 or risk >= 5:
            score -= 1.5
        else:
            score -= 0.5

    diff_pct = float(metrics.get("portfolio_difference_pct") or 0)
    if diff_pct > 10:
        score -= 15
    elif diff_pct > 5:
        score -= 10
    elif diff_pct > 1:
        score -= 5

    score -= min(proposed_plan_count, 5)

    if aws_audit_age_days is None or aws_audit_age_days > 7:
        score -= 5
    if crypto_audit_age_days is None or crypto_audit_age_days > 7:
        score -= 5

    open_findings = int(metrics.get("open_findings") or 0)
    if open_findings > 10:
        score -= 5
    elif open_findings > 5:
        score -= 2

    return max(0, min(100, round(score)))


def _audit_age_days(created_at: str | None) -> int | None:
    dt = _parse_iso(created_at)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).days


def generate_executive_report(*, report_id: str | None = None) -> dict[str, Any]:
    """
    Aggregate audits, metrics, and action plans into a weekly priorities report.
    Read-only — no execution performed.
    """
    now = datetime.now(timezone.utc)
    metrics = collect_daily_metrics()

    aws_audits = list_audit_runs(limit=5)
    crypto_audits = list_crypto_audit_runs(limit=5)
    action_plan_summaries = list_action_plans(limit=20)

    full_plans: list[dict[str, Any]] = []
    for summary in action_plan_summaries:
        from app.jarvis.mvp.action_plan_persistence import get_action_plan

        detail = get_action_plan(summary["plan_id"])
        if detail:
            full_plans.append(detail)

    scored_items: list[dict[str, Any]] = []

    if aws_audits:
        latest_aws = get_audit_run(aws_audits[0]["audit_id"])
        if latest_aws:
            scored_items.extend(_aws_finding_items(latest_aws))

    if crypto_audits:
        latest_crypto = get_crypto_audit_run(crypto_audits[0]["audit_id"])
        if latest_crypto:
            scored_items.extend(_crypto_finding_items(latest_crypto))

    scored_items.extend(_action_plan_items(full_plans))

    if not scored_items:
        scored_items.append(
            _priority_item(
                title="Run AWS and crypto audits",
                reason="No recent audit findings available for prioritization",
                expected_impact="Establishes baseline for weekly executive priorities",
                estimated_savings_usd=0.0,
                risk_if_ignored="Operating without visibility into infrastructure and portfolio health",
                impact=6,
                risk=5,
                effort=3,
                source_kind="aws_resource",
            )
        )

    history_index = get_decision_history_index()
    scored_items = [apply_decision_adjustments(item, history_index) for item in scored_items]

    open_followups = list_open_followups()
    followup_review = get_followup_review(followups=open_followups)
    if followup_review.get("has_high_severity"):
        boost = 1.25
        for item in scored_items:
            item["priority_score"] = round(float(item.get("priority_score") or 0) * boost, 2)
            item["reason"] = f"{item.get('reason', '')} [Elevated: high-severity follow-ups open]".strip()

    scored_items.sort(key=lambda x: x["priority_score"], reverse=True)

    lessons_learned = generate_lessons_learned(history_index)
    decision_intelligence = get_decision_analytics()

    top_priorities = [
        _public_item(item, priority=idx + 1) for idx, item in enumerate(scored_items[:5])
    ]

    quick_wins = [
        _public_item(item)
        for item in scored_items
        if int(item.get("effort") or 10) <= 3 and int(item.get("impact") or 0) >= 6
    ][:5]

    strategic_items = [
        _public_item(item)
        for item in scored_items
        if int(item.get("effort") or 0) >= 5 and int(item.get("impact") or 0) >= 5
    ][:5]

    blocked_items: list[dict[str, Any]] = []
    aws_age = _audit_age_days(aws_audits[0]["created_at"]) if aws_audits else None
    crypto_age = _audit_age_days(crypto_audits[0]["created_at"]) if crypto_audits else None

    if aws_age is None or aws_age > 14:
        blocked_items.append(
            {
                "title": "AWS audit data stale or missing",
                "reason": "No recent AWS audit — priorities may be incomplete",
                "blocked_by": "Run AWS infrastructure audit to refresh findings",
            }
        )
    if crypto_age is None or crypto_age > 14:
        blocked_items.append(
            {
                "title": "Crypto audit data stale or missing",
                "reason": "No recent crypto audit — portfolio priorities may be incomplete",
                "blocked_by": "Run crypto portfolio audit to refresh findings",
            }
        )
    for plan in full_plans:
        if str(plan.get("status")) == "proposed" and str(plan.get("severity")).lower() == "critical":
            blocked_items.append(
                {
                    "title": f"Critical action plan awaiting review ({plan.get('plan_id', '')[:8]}…)",
                    "reason": "Critical remediation plan requires human approval before any manual steps",
                    "blocked_by": "Human review and approval required",
                }
            )

    for followup in open_followups:
        sev = str(followup.get("severity") or "").lower()
        if sev not in ("high", "critical"):
            continue
        if str(followup.get("source_type")) in ("initiative", "action_plan", "decision"):
            blocked_items.append(
                {
                    "title": followup.get("title") or "Follow-up requires attention",
                    "reason": followup.get("description") or "Open high-severity follow-up",
                    "blocked_by": "Human review required — no autonomous execution",
                }
            )

    proposed_count = sum(1 for p in full_plans if str(p.get("status")) == "proposed")
    health_score = calculate_health_score(
        scored_items=scored_items,
        metrics=metrics,
        aws_audit_age_days=aws_age,
        crypto_audit_age_days=crypto_age,
        proposed_plan_count=proposed_count,
    )

    total_savings = sum(float(item.get("estimated_savings_usd") or 0) for item in scored_items)

    initiatives = list_all_initiatives()
    execution_review = get_execution_review(initiatives=initiatives)
    execution_status = get_execution_status(initiatives=initiatives)

    for obj in list_all_strategic_objectives():
        if str(obj.get("status")) not in ("cancelled",):
            record_objective_metric_snapshot(objective_id=obj["objective_id"])
    strategic_alignment = get_strategic_alignment()

    for blocked_obj in strategic_alignment.get("blocked_objectives") or []:
        blocked_items.append(
            {
                "title": f"Objective at risk: {blocked_obj.get('title')}",
                "reason": blocked_obj.get("reason") or "Strategic objective blocked or overdue",
                "blocked_by": "Human review required — linked initiatives or timeline",
            }
        )

    return {
        "report_id": report_id or str(uuid.uuid4()),
        "generated_at": now.isoformat(),
        "overall_health_score": health_score,
        "top_priorities": top_priorities,
        "quick_wins": quick_wins,
        "strategic_items": strategic_items,
        "blocked_items": blocked_items,
        "lessons_learned": lessons_learned,
        "decision_intelligence": {
            "decision_success_rate": decision_intelligence.get("decision_success_rate"),
            "approved_count": decision_intelligence.get("approved_count"),
            "rejected_count": decision_intelligence.get("rejected_count"),
            "deferred_count": decision_intelligence.get("deferred_count"),
            "repeated_findings_count": decision_intelligence.get("repeated_findings_count"),
        },
        "total_potential_savings_usd": round(total_savings, 2),
        "inputs_summary": {
            "aws_audits_considered": len(aws_audits),
            "crypto_audits_considered": len(crypto_audits),
            "action_plans_considered": len(full_plans),
            "findings_scored": len(scored_items),
            "decisions_considered": decision_intelligence.get("total_decisions", 0),
            "initiatives_considered": len(initiatives),
        },
        "execution_review": {
            "active": execution_review["active"],
            "blocked": execution_review["blocked"],
            "overdue": execution_review["overdue"],
            "stalled": execution_review["stalled"],
            "completed_this_month": execution_review["completed_this_month"],
            "top_risk": execution_review.get("top_risk"),
        },
        "execution_status": execution_status,
        "followup_review": followup_review,
        "strategic_alignment": strategic_alignment,
        "read_only": True,
        "execution_performed": False,
    }
