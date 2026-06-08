"""Action Planner Agent — generates remediation recommendations from audit findings.

Read-only: no infrastructure changes, trades, or balance modifications.
All outputs are proposals for human review.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from app.jarvis.mvp.audit_persistence import get_audit_run
from app.jarvis.mvp.crypto_audit_persistence import get_crypto_audit_run

SourceType = Literal["aws_audit", "crypto_audit", "executive_dashboard"]

_SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _max_severity(*severities: str) -> str:
    best = "low"
    for sev in severities:
        key = str(sev or "low").lower()
        if _SEVERITY_ORDER.get(key, 0) > _SEVERITY_ORDER.get(best, 0):
            best = key
    return best


def _action(
    *,
    title: str,
    description: str,
    impact: str,
    risk: str,
    manual_steps: list[str],
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "impact": impact,
        "risk": risk,
        "manual_steps": manual_steps,
    }


def _plans_from_aws_audit(audit: dict[str, Any]) -> tuple[list[dict[str, Any]], str, float, str]:
    """Build action items from AWS audit findings."""
    actions: list[dict[str, Any]] = []
    severities: list[str] = []
    estimated_savings = float(audit.get("estimated_monthly_savings") or 0.0)

    for finding in audit.get("cost_findings") or []:
        category = str(finding.get("category") or "").lower()
        sev = str(finding.get("severity") or "medium").lower()
        severities.append(sev)
        savings = float(finding.get("estimated_monthly_savings_usd") or 0)

        if category == "ebs":
            actions.append(
                _action(
                    title="Remove unattached EBS volumes after snapshot",
                    description=finding.get("finding", "Unattached EBS volumes detected"),
                    impact=f"Estimated monthly savings: ${savings:,.2f}",
                    risk="Low if verified unused; data loss if volume still needed",
                    manual_steps=[
                        "Identify each unattached volume in AWS Console or CLI (read-only list first).",
                        "Confirm no application depends on the volume (check tags, naming, change history).",
                        "Create a snapshot of each volume before any deletion.",
                        "After snapshot verification, delete the unattached volume manually.",
                        "Re-run AWS audit to confirm savings.",
                    ],
                )
            )
        elif category == "snapshots":
            actions.append(
                _action(
                    title="Archive or delete stale EBS snapshots",
                    description=finding.get("finding", "Old EBS snapshots detected"),
                    impact=f"Estimated monthly savings: ${savings:,.2f}",
                    risk="Medium — may affect disaster recovery if snapshots are still required",
                    manual_steps=[
                        "List snapshots older than 90 days and review retention policy.",
                        "Confirm with owners whether each snapshot is still required.",
                        "Copy critical snapshots to long-term archive if needed.",
                        "Delete obsolete snapshots manually.",
                        "Document retention decisions for compliance.",
                    ],
                )
            )
        elif category == "eip":
            actions.append(
                _action(
                    title="Release unattached Elastic IPs",
                    description=finding.get("finding", "Unattached Elastic IPs detected"),
                    impact=f"Estimated monthly savings: ${savings:,.2f}",
                    risk="Low if truly unused; service disruption if re-associated incorrectly",
                    manual_steps=[
                        "List unattached Elastic IPs in EC2 console.",
                        "Verify no DNS records or firewall rules reference these IPs.",
                        "Release each unattached EIP manually.",
                        "Update infrastructure documentation.",
                    ],
                )
            )
        else:
            actions.append(
                _action(
                    title="Review cost optimization finding",
                    description=str(finding.get("finding") or "Cost finding requires review"),
                    impact=f"Potential monthly savings: ${savings:,.2f}",
                    risk="Varies — validate before any resource change",
                    manual_steps=[
                        "Review the finding details in the audit report.",
                        "Assess business impact of remediation.",
                        "Plan manual changes with owner approval.",
                    ],
                )
            )

    for finding in audit.get("security_findings") or []:
        category = str(finding.get("category") or "").lower()
        sev = str(finding.get("severity") or "high").lower()
        severities.append(sev)
        count = int(finding.get("count") or 0)

        if category == "security_groups":
            actions.append(
                _action(
                    title="Restrict open security group ingress",
                    description=finding.get("finding", "Risky security group exposure detected"),
                    impact=f"Reduces attack surface for {count} security group(s)",
                    risk="Medium — overly restrictive rules may block legitimate traffic",
                    manual_steps=[
                        "List security groups with 0.0.0.0/0 ingress on admin/database ports.",
                        "Identify affected services and required source IP ranges.",
                        "Draft tightened ingress rules (least privilege).",
                        "Apply changes manually in AWS Console with change window approval.",
                        "Validate service connectivity after change.",
                        "Re-run security group inventory audit.",
                    ],
                )
            )
        else:
            actions.append(
                _action(
                    title="Address security finding",
                    description=str(finding.get("finding") or "Security finding requires review"),
                    impact="Improves infrastructure security posture",
                    risk="Medium — validate blast radius before changes",
                    manual_steps=[
                        "Review finding in audit detail.",
                        "Identify affected resources and owners.",
                        "Plan manual remediation with security team approval.",
                    ],
                )
            )

    for finding in audit.get("resource_findings") or []:
        category = str(finding.get("category") or "").lower()
        sev = str(finding.get("severity") or "low").lower()
        severities.append(sev)
        count = int(finding.get("count") or 0)

        if category == "ec2":
            actions.append(
                _action(
                    title="Review stopped EC2 instances",
                    description=finding.get("finding", "Stopped EC2 instances incurring cost"),
                    impact=f"May reduce storage cost for {count} instance(s)",
                    risk="Low to medium — instances may be intentionally stopped",
                    manual_steps=[
                        "List stopped instances and review last activity dates.",
                        "Contact owners to confirm decommission status.",
                        "Snapshot volumes if terminating.",
                        "Terminate or resize instances manually after approval.",
                    ],
                )
            )
        elif category == "tagging":
            required = finding.get("required_tags") or ["Environment", "Project", "Owner"]
            tag_list = ", ".join(required) if isinstance(required, list) else str(required)
            actions.append(
                _action(
                    title="Apply missing resource tags",
                    description=finding.get("finding", "Resources missing required tags"),
                    impact=f"Improves cost allocation and governance for {count} resource(s)",
                    risk="Low — tagging only, no runtime impact",
                    manual_steps=[
                        f"Identify resources missing tags: {tag_list}.",
                        "Gather correct tag values from resource owners.",
                        "Apply tags manually via AWS Console or approved tagging script.",
                        "Re-run tag audit to confirm compliance.",
                    ],
                )
            )
        else:
            actions.append(
                _action(
                    title="Review resource finding",
                    description=str(finding.get("finding") or "Resource finding requires review"),
                    impact="Improves resource hygiene and governance",
                    risk="Low to medium depending on resource type",
                    manual_steps=[
                        "Review finding in audit detail.",
                        "Coordinate with resource owners.",
                        "Apply manual remediation after approval.",
                    ],
                )
            )

    severity = _max_severity(*(severities or ["low"]))
    risk_parts: list[str] = []
    if audit.get("security_findings"):
        risk_parts.append("reduced public exposure risk")
    if estimated_savings > 0:
        risk_parts.append(f"${estimated_savings:,.2f}/mo cost waste addressed")
    if audit.get("resource_findings"):
        risk_parts.append("improved tagging and resource hygiene")
    risk_reduction = (
        "; ".join(risk_parts) if risk_parts else "Operational visibility improved through documented manual steps"
    )
    return actions, severity, estimated_savings, risk_reduction


def _plans_from_crypto_audit(audit: dict[str, Any]) -> tuple[list[dict[str, Any]], str, float, str]:
    """Build action items from crypto audit findings."""
    actions: list[dict[str, Any]] = []
    severities: list[str] = []

    all_findings: list[dict[str, Any]] = []
    for key in ("wallet_findings", "position_findings", "valuation_findings", "price_feed_findings"):
        all_findings.extend(audit.get(key) or [])

    for finding in all_findings:
        ftype = str(finding.get("type") or "").lower()
        sev = str(finding.get("severity") or "medium").lower()
        severities.append(sev)
        currency = finding.get("currency") or ""

        if ftype == "missing_asset":
            actions.append(
                _action(
                    title="Verify exchange sync for missing asset",
                    description=finding.get("finding", f"{currency} missing in dashboard cache"),
                    impact="Restores portfolio accuracy and reconciliation confidence",
                    risk="Low — read-only verification; no trades executed",
                    manual_steps=[
                        f"Check exchange balance for {currency or 'asset'} in Crypto.com UI.",
                        "Review exchange_sync ingestion logs for recent failures.",
                        "Trigger manual portfolio cache refresh (approved process only).",
                        "Compare per-asset balances after refresh.",
                        "Re-run crypto audit to confirm reconciliation.",
                    ],
                )
            )
        elif ftype == "balance_mismatch":
            diff_pct = float(finding.get("difference_pct") or audit.get("portfolio_difference_pct") or 0)
            actions.append(
                _action(
                    title="Reconcile portfolio balance mismatch",
                    description=finding.get("finding", "Exchange vs dashboard balance mismatch"),
                    impact=f"Addresses portfolio difference ({diff_pct}% if applicable)",
                    risk="Low — diagnostic only until human approves any trading action",
                    manual_steps=[
                        "Refresh exchange portfolio cache via approved sync process.",
                        "Compare per-asset balances between exchange and dashboard.",
                        "Validate price feed timestamps for valuation differences.",
                        "Check recent trade history for unprocessed fills.",
                        "Document root cause before any corrective action.",
                    ],
                )
            )
        elif ftype == "valuation_mismatch":
            actions.append(
                _action(
                    title="Validate valuation and price feed source",
                    description=finding.get("finding", f"{currency} USD valuation mismatch"),
                    impact="Aligns portfolio valuation across systems",
                    risk="Low — no balance or trade changes",
                    manual_steps=[
                        f"Compare {currency or 'asset'} price from exchange API vs dashboard cache.",
                        "Check price feed latency and symbol coverage.",
                        "Identify stale or missing ticker symbols.",
                        "Re-run crypto audit after feed validation.",
                    ],
                )
            )
        elif ftype == "stale_cache":
            actions.append(
                _action(
                    title="Refresh stale portfolio cache",
                    description=finding.get("finding", "Portfolio cache may be stale"),
                    impact="Improves data freshness for reconciliation",
                    risk="Low — cache refresh only, no trades",
                    manual_steps=[
                        "Check cache_age_seconds in audit detail.",
                        "Run approved exchange_sync / cache refresh procedure.",
                        "Verify row_count and timestamps after refresh.",
                        "Re-run crypto audit.",
                    ],
                )
            )
        elif ftype == "stale_price_feed":
            actions.append(
                _action(
                    title="Investigate stale price feed",
                    description=finding.get("finding", "Price feed may be stale"),
                    impact="Restores accurate USD valuations",
                    risk="Low — diagnostic and feed validation only",
                    manual_steps=[
                        "Check Crypto.com public ticker API connectivity.",
                        "Review symbol_count and latency_ms from audit.",
                        "Compare feeds from multiple sources if available.",
                        "Escalate to ops if feed remains stale.",
                    ],
                )
            )
        elif ftype in ("missing_position", "duplicate_position", "orphan_trade"):
            actions.append(
                _action(
                    title=f"Review position/trade finding ({ftype})",
                    description=str(finding.get("finding") or ftype),
                    impact="Aligns open positions with exchange state",
                    risk="Medium — may indicate sync or ingestion issues",
                    manual_steps=[
                        "Compare open positions on exchange vs dashboard.",
                        "Review trade history for orphan or duplicate entries.",
                        "Check ingestion pipeline logs.",
                        "Re-run crypto audit after investigation.",
                    ],
                )
            )
        else:
            actions.append(
                _action(
                    title="Review crypto audit finding",
                    description=str(finding.get("finding") or ftype or "Finding requires review"),
                    impact="Improves portfolio reconciliation accuracy",
                    risk="Low — manual investigation only",
                    manual_steps=[
                        "Review finding in crypto audit detail.",
                        "Follow recommended audit steps from report.",
                        "Re-run crypto audit after resolution.",
                    ],
                )
            )

    if not actions:
        for rec in audit.get("recommendations") or []:
            actions.append(
                _action(
                    title="Follow audit recommendation",
                    description=str(rec),
                    impact="Addresses identified portfolio or feed issue",
                    risk="Low — human-reviewed manual steps only",
                    manual_steps=[str(rec), "Document outcome and re-run crypto audit."],
                )
            )
            severities.append("medium")

    severity = _max_severity(*(severities or ["low"]))
    diff_pct = float(audit.get("portfolio_difference_pct") or 0)
    risk_reduction = (
        f"Portfolio reconciliation accuracy improved (current diff {diff_pct}%)"
        if diff_pct > 0
        else "Portfolio data quality and feed reliability improved"
    )
    return actions, severity, 0.0, risk_reduction


def _plans_from_executive_dashboard(dashboard: dict[str, Any]) -> tuple[list[dict[str, Any]], str, float, str]:
    """Build action items from executive dashboard health signals."""
    actions: list[dict[str, Any]] = []
    severities: list[str] = []

    infra = dashboard.get("infrastructure") or {}
    security = dashboard.get("security") or {}
    activity = dashboard.get("jarvis_activity") or {}
    crypto = dashboard.get("crypto_health") or {}

    open_findings = int(security.get("open_findings") or 0)
    critical_findings = int(security.get("critical_findings") or 0)
    sg_exposed = int(security.get("security_groups_exposed_0_0_0_0") or 0)
    untagged = int(security.get("untagged_resources") or 0)
    failed_tasks = int(activity.get("failed_tasks") or 0)
    diff_pct = float(crypto.get("difference_pct") or 0)
    recon_status = str(crypto.get("reconciliation_status") or "unknown")
    aws_monthly = float(infra.get("aws_monthly_spend") or 0)

    if critical_findings > 0 or sg_exposed > 0:
        sev = "critical" if critical_findings > 0 else "high"
        severities.append(sev)
        actions.append(
            _action(
                title="Address critical infrastructure security findings",
                description=f"{open_findings} open finding(s), {critical_findings} critical, {sg_exposed} SG(s) exposed to 0.0.0.0/0",
                impact="Reduces public attack surface and compliance risk",
                risk="Medium — network rule changes require validation",
                manual_steps=[
                    "Run a full AWS infrastructure audit from Jarvis Tasks.",
                    "Review security group findings and identify affected services.",
                    "Draft least-privilege ingress rules with owner approval.",
                    "Apply changes manually during an approved change window.",
                    "Generate a new action plan from the updated audit.",
                ],
            )
        )

    if untagged > 0:
        severities.append("medium")
        actions.append(
            _action(
                title="Apply missing AWS resource tags",
                description=f"{untagged} resource(s) missing required tags",
                impact="Improves cost allocation and governance visibility",
                risk="Low — tagging only",
                manual_steps=[
                    "Run AWS tag audit to list untagged resources.",
                    "Collect Environment, Project, and Owner values from owners.",
                    "Apply tags manually via AWS Console.",
                    "Re-check executive dashboard security metrics.",
                ],
            )
        )

    if recon_status in ("mismatch", "critical") or diff_pct > 5:
        sev = "critical" if recon_status == "critical" or diff_pct > 10 else "high"
        severities.append(sev)
        actions.append(
            _action(
                title="Reconcile portfolio mismatch from executive metrics",
                description=f"Crypto reconciliation status: {recon_status} ({diff_pct}% difference)",
                impact="Restores confidence in portfolio reporting",
                risk="Low — diagnostic and cache refresh only; no trades",
                manual_steps=[
                    "Run a crypto portfolio audit from Jarvis Tasks.",
                    "Refresh portfolio cache via approved sync procedure.",
                    "Compare exchange vs dashboard balances per asset.",
                    "Generate action plan from crypto audit for detailed steps.",
                ],
            )
        )

    if failed_tasks > 0:
        severities.append("medium")
        actions.append(
            _action(
                title="Investigate failed Jarvis tasks",
                description=f"{failed_tasks} Jarvis task(s) failed recently",
                impact="Improves automation reliability and observability",
                risk="Low — log review only",
                manual_steps=[
                    "Review failed tasks in /jarvis task history.",
                    "Check tool errors and Bedrock connectivity.",
                    "Document root cause and retry read-only diagnostics.",
                ],
            )
        )

    if aws_monthly > 0 and open_findings > 0:
        severities.append("medium")
        actions.append(
            _action(
                title="Review AWS cost optimization opportunities",
                description=f"Monthly AWS spend ${aws_monthly:,.2f} with {open_findings} open finding(s)",
                impact="Potential infrastructure cost reduction",
                risk="Low to medium — validate before deleting resources",
                manual_steps=[
                    "Run AWS infrastructure audit for cost findings.",
                    "Review unattached EBS, snapshots, and Elastic IPs.",
                    "Generate action plan from AWS audit for savings estimates.",
                ],
            )
        )

    severity = _max_severity(*(severities or ["low"]))
    risk_parts: list[str] = []
    if critical_findings or sg_exposed:
        risk_parts.append("reduced security exposure")
    if diff_pct > 0:
        risk_parts.append(f"portfolio accuracy (diff {diff_pct}%)")
    if untagged:
        risk_parts.append("improved governance tagging")
    risk_reduction = (
        "; ".join(risk_parts) if risk_parts else "Executive visibility improved through documented manual steps"
    )
    return actions, severity, 0.0, risk_reduction


def _primary_finding_summary(source_type: SourceType, audit: dict[str, Any]) -> str:
    """One-line summary of the top finding for alerts."""
    if source_type == "executive_dashboard":
        security = audit.get("security") or {}
        crypto = audit.get("crypto_health") or {}
        if int(security.get("critical_findings") or 0) > 0:
            return f"{security['critical_findings']} critical infrastructure finding(s)"
        if str(crypto.get("reconciliation_status") or "") in ("mismatch", "critical"):
            return f"Portfolio reconciliation: {crypto.get('reconciliation_status')} ({crypto.get('difference_pct')}%)"
        if int(security.get("open_findings") or 0) > 0:
            return f"{security['open_findings']} open finding(s) on executive dashboard"
        return "Executive dashboard signals require review"
    if source_type == "aws_audit":
        for group in ("security_findings", "cost_findings", "resource_findings"):
            items = audit.get(group) or []
            if items:
                return str(items[0].get("finding") or "AWS audit findings require review")
        return "AWS audit completed with recommendations"
    for key in ("wallet_findings", "valuation_findings", "position_findings", "price_feed_findings"):
        items = audit.get(key) or []
        for item in items:
            if str(item.get("severity") or "").lower() == "critical":
                return str(item.get("finding") or "Critical crypto finding")
        if items:
            return str(items[0].get("finding") or "Crypto audit findings require review")
    return "Crypto audit completed with recommendations"


def generate_action_plan(
    *,
    source_type: SourceType,
    source_id: str,
    plan_id: str | None = None,
) -> dict[str, Any]:
    """
    Generate a remediation plan from an existing audit run.
    Does not execute any remediation — recommendations only.
    """
    if source_type == "aws_audit":
        audit = get_audit_run(source_id)
        if audit is None:
            raise ValueError(f"AWS audit not found: {source_id}")
        actions, severity, savings, risk_reduction = _plans_from_aws_audit(audit)
        finding_summary = _primary_finding_summary(source_type, audit)
    elif source_type == "crypto_audit":
        audit = get_crypto_audit_run(source_id)
        if audit is None:
            raise ValueError(f"Crypto audit not found: {source_id}")
        actions, severity, savings, risk_reduction = _plans_from_crypto_audit(audit)
        finding_summary = _primary_finding_summary(source_type, audit)
    elif source_type == "executive_dashboard":
        from app.jarvis.mvp.metrics_persistence import get_executive_dashboard

        dashboard = get_executive_dashboard()
        source_key = source_id if source_id != "current" else str(
            (dashboard.get("crypto_health") or {}).get("last_reconciliation_date") or "current"
        )
        actions, severity, savings, risk_reduction = _plans_from_executive_dashboard(dashboard)
        finding_summary = _primary_finding_summary(source_type, dashboard)
        audit = dashboard
        source_id = source_key
    else:
        raise ValueError(f"Unsupported source_type: {source_type}")

    if not actions:
        actions.append(
            _action(
                title="No actionable findings",
                description="Audit completed without items requiring remediation steps.",
                impact="No immediate action required",
                risk="None",
                manual_steps=["Review audit report for informational items.", "Schedule next audit as needed."],
            )
        )
        severity = "low"

    return {
        "plan_id": plan_id or str(uuid.uuid4()),
        "severity": severity,
        "estimated_savings_usd": round(savings, 2),
        "estimated_risk_reduction": risk_reduction,
        "actions": actions,
        "source_type": source_type,
        "source_id": source_id,
        "finding_summary": finding_summary,
        "read_only": True,
        "execution_performed": False,
    }
