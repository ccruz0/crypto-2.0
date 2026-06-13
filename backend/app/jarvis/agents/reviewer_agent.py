"""Code review agent for Jarvis Phase 4 patch workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.jarvis.execution.safety import SafetyLevel, classify_phase4_action, classify_text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _score_dimension(name: str, issues: list[str], *, weight: int) -> tuple[int, list[str]]:
    penalty = min(len(issues) * weight, weight * 3)
    return penalty, [f"{name}: {i}" for i in issues]


def review_patch(
    *,
    patch: dict[str, Any],
    repository_analysis: dict[str, Any] | None = None,
    test_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Review a proposed patch for correctness, safety, security, scope, and policy."""
    objective = patch.get("objective", "")
    target_files = patch.get("target_files", [])
    risk = patch.get("risk_assessment", {})
    findings: list[dict[str, str]] = []
    issues_by_dim: dict[str, list[str]] = {
        "correctness": [],
        "safety": [],
        "security": [],
        "scope": [],
        "policy": [],
        "deployment": [],
    }

    if not patch.get("unified_diff"):
        issues_by_dim["correctness"].append("empty unified diff")
    if patch.get("estimated_impact", {}).get("auto_apply"):
        issues_by_dim["policy"].append("patch marked for auto-apply — forbidden in Phase 4")
    if classify_text(objective) == SafetyLevel.FORBIDDEN:
        issues_by_dim["policy"].append("objective classified as FORBIDDEN")
    if classify_phase4_action("patch_application") != SafetyLevel.NEEDS_APPROVAL:
        issues_by_dim["policy"].append("patch application must require approval")
    if len(target_files) > 5:
        issues_by_dim["scope"].append(f"large scope: {len(target_files)} files")
    if any("secret" in f.lower() or ".env" in f for f in target_files):
        issues_by_dim["security"].append("targets sensitive paths")
    if any("deploy" in f.lower() for f in target_files):
        issues_by_dim["deployment"].append("touches deployment scripts")
    if test_results and not test_results.get("ok", True):
        issues_by_dim["correctness"].append(f"tests failed: {test_results.get('failed_count', 0)}")

    total_penalty = 0
    for dim, issues in issues_by_dim.items():
        penalty, dim_findings = _score_dimension(dim, issues, weight=10)
        total_penalty += penalty
        for f in dim_findings:
            findings.append({"dimension": dim, "finding": f, "severity": "high" if penalty >= 20 else "medium"})

    base_score = int(risk.get("risk_score", 30))
    risk_score = min(100, max(0, base_score + total_penalty // 2))
    if risk_score >= 70:
        recommendation = "reject"
    elif risk_score >= 45:
        recommendation = "needs_approval"
    else:
        recommendation = "approve_with_review"

    report_md = _format_review_markdown(objective, findings, risk_score, recommendation)
    return {
        "agent": "reviewer_agent",
        "review_report": report_md,
        "findings": findings,
        "risk_score": risk_score,
        "approval_recommendation": recommendation,
        "dimensions_reviewed": list(issues_by_dim.keys()),
        "policy_compliant": not any("FORBIDDEN" in f["finding"] for f in findings),
        "patch_application_allowed": False,
        "created_at": _now_iso(),
        "read_only": True,
    }


def _format_review_markdown(objective: str, findings: list[dict[str, str]], risk_score: int, recommendation: str) -> str:
    lines = [
        "# Patch Review Report",
        "",
        f"**Objective:** {objective[:300]}",
        f"**Risk Score:** {risk_score}/100",
        f"**Recommendation:** {recommendation}",
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines.append("- No blocking findings detected.")
    else:
        for f in findings:
            lines.append(f"- [{f['severity'].upper()}] {f['dimension']}: {f['finding']}")
    lines.extend(["", "## Policy", "", "- Patch application: NEEDS_APPROVAL (not auto-applied)", "- PR creation: NEEDS_APPROVAL", "- Merge/Deploy/Trading: FORBIDDEN"])
    return "\n".join(lines)
