"""Compile AWS Auditor findings from read-only inventory tools."""

from __future__ import annotations

from typing import Any

from app.jarvis.mvp.aws_auditor_tools import AWS_AUDITOR_TOOLS, run_aws_auditor_tool

_AUDIT_TOOL_ORDER = (
    "get_ec2_inventory",
    "get_ebs_inventory",
    "get_snapshot_inventory",
    "get_eip_inventory",
    "get_security_group_inventory",
    "get_cost_summary",
    "get_resource_tag_audit",
)


def is_aws_audit_task(task: str) -> bool:
    """Return True when the task requests an AWS infrastructure audit."""
    text = (task or "").lower()
    triggers = (
        "aws infrastructure audit",
        "run aws infrastructure audit",
        "aws audit",
        "infrastructure audit",
        "audit aws infrastructure",
        "audit aws resources",
    )
    return any(t in text for t in triggers)


def run_aws_audit() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run all AWS auditor tools and compile structured findings."""
    tool_results: list[dict[str, Any]] = []
    for tool in _AUDIT_TOOL_ORDER:
        tool_results.append(run_aws_auditor_tool(tool))

    findings = compile_audit_findings(tool_results)
    return tool_results, findings


def compile_audit_findings(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the structured audit output from tool results."""
    cost_findings: list[dict[str, Any]] = []
    security_findings: list[dict[str, Any]] = []
    resource_findings: list[dict[str, Any]] = []
    recommendations: list[str] = []
    estimated_savings = 0.0

    by_tool = {r.get("tool"): r for r in tool_results if isinstance(r, dict)}

    ec2 = by_tool.get("get_ec2_inventory") or {}
    if ec2.get("success"):
        if ec2.get("stopped_count", 0) > 0:
            resource_findings.append(
                {
                    "severity": "medium",
                    "category": "ec2",
                    "finding": f"{ec2['stopped_count']} stopped EC2 instance(s) incurring EBS/storage cost",
                    "count": ec2["stopped_count"],
                }
            )
            recommendations.append(
                "Review stopped EC2 instances; terminate or snapshot-and-delete if no longer needed."
            )
        if ec2.get("untagged_count", 0) > 0:
            resource_findings.append(
                {
                    "severity": "low",
                    "category": "tagging",
                    "finding": f"{ec2['untagged_count']} EC2 instance(s) without tags",
                    "count": ec2["untagged_count"],
                }
            )

    ebs = by_tool.get("get_ebs_inventory") or {}
    if ebs.get("success") and ebs.get("unattached_count", 0) > 0:
        waste = float(ebs.get("estimated_monthly_waste_usd") or 0)
        estimated_savings += waste
        cost_findings.append(
            {
                "severity": "high",
                "category": "ebs",
                "finding": f"{ebs['unattached_count']} unattached EBS volume(s)",
                "estimated_monthly_savings_usd": waste,
            }
        )
        recommendations.append("Delete or snapshot unattached EBS volumes after verification.")

    snaps = by_tool.get("get_snapshot_inventory") or {}
    if snaps.get("success") and snaps.get("old_count", 0) > 0:
        waste = float(snaps.get("estimated_monthly_waste_usd") or 0)
        estimated_savings += waste
        cost_findings.append(
            {
                "severity": "medium",
                "category": "snapshots",
                "finding": f"{snaps['old_count']} EBS snapshot(s) older than 90 days",
                "estimated_monthly_savings_usd": waste,
            }
        )
        recommendations.append("Archive or delete old EBS snapshots no longer required for recovery.")

    eips = by_tool.get("get_eip_inventory") or {}
    if eips.get("success") and eips.get("unattached_count", 0) > 0:
        waste = float(eips.get("estimated_monthly_waste_usd") or 0)
        estimated_savings += waste
        cost_findings.append(
            {
                "severity": "medium",
                "category": "eip",
                "finding": f"{eips['unattached_count']} unattached Elastic IP(s)",
                "estimated_monthly_savings_usd": waste,
            }
        )
        recommendations.append("Release unattached Elastic IPs to avoid hourly charges.")

    sgs = by_tool.get("get_security_group_inventory") or {}
    if sgs.get("success") and sgs.get("risky_count", 0) > 0:
        security_findings.append(
            {
                "severity": "high",
                "category": "security_groups",
                "finding": f"{sgs['risky_count']} security group(s) with risky public exposure",
                "count": sgs["risky_count"],
            }
        )
        recommendations.append(
            "Restrict security group ingress rules; avoid 0.0.0.0/0 on admin/database ports."
        )

    tags = by_tool.get("get_resource_tag_audit") or {}
    if tags.get("success") and tags.get("untagged_count", 0) > 0:
        resource_findings.append(
            {
                "severity": "low",
                "category": "tagging",
                "finding": f"{tags['untagged_count']} resource(s) missing required tags",
                "required_tags": tags.get("required_tags"),
                "count": tags["untagged_count"],
            }
        )
        recommendations.append("Apply Environment, Project, and Owner tags for cost allocation.")

    cost = by_tool.get("get_cost_summary") or {}
    total_spend = float(cost.get("total_usd") or 0) if cost.get("success") else None

    summary = {
        "total_resources_scanned": sum(
            1
            for r in tool_results
            if isinstance(r, dict) and r.get("success") and r.get("tool") in AWS_AUDITOR_TOOLS
        ),
        "tools_executed": len(tool_results),
        "tools_succeeded": sum(1 for r in tool_results if r.get("success")),
        "cost_findings_count": len(cost_findings),
        "security_findings_count": len(security_findings),
        "resource_findings_count": len(resource_findings),
        "total_30d_spend_usd": total_spend,
        "read_only": True,
    }

    return {
        "summary": summary,
        "cost_findings": cost_findings,
        "security_findings": security_findings,
        "resource_findings": resource_findings,
        "recommendations": recommendations,
        "estimated_monthly_savings": round(estimated_savings, 2),
    }
