"""Read-only evidence collection for Autonomous Coding Workflow."""

from __future__ import annotations

import logging
from typing import Any

from app.jarvis.agents.repository_agent import investigate_objective
from app.jarvis.execution.safety import SafetyLevel, classify_change_objective, classify_text
from app.jarvis.github.integration import github_readonly_summary
from app.jarvis.investigations.investigation_runner import collect_evidence
from app.jarvis.repository.graph import build_repository_graph
from app.jarvis.repository.persistence import refresh_repository_metadata

logger = logging.getLogger(__name__)

# Read-only production evidence — no write tools.
_ACW_READ_ONLY_COLLECTOR_LIMIT = 3


def _summarize_production_evidence(
    evidence_items: list[Any],
    tool_outputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten production evidence into a JSON-serializable summary."""
    summary: list[dict[str, Any]] = []
    for item in evidence_items[:20]:
        summary.append(
            {
                "source": getattr(item, "source", "") or item.get("source", "") if isinstance(item, dict) else "",
                "reference": getattr(item, "reference", "") or "",
                "detail": (getattr(item, "detail", "") or "")[:500],
                "confidence": getattr(item, "confidence", "") or "",
            }
        )
    for out in tool_outputs[:_ACW_READ_ONLY_COLLECTOR_LIMIT]:
        if out.get("ok"):
            summary.append(
                {
                    "source": "production_tool",
                    "reference": out.get("tool", ""),
                    "detail": str(out.get("summary") or out.get("message") or "")[:500],
                    "confidence": "medium",
                }
            )
    return summary


def collect_acw_evidence(
    objective: str,
    *,
    target_files: list[str] | None = None,
    include_production: bool = True,
) -> dict[str, Any]:
    """
    Fuse repository context, code references, optional read-only production evidence,
    and safety classification. No write tools are invoked.
    """
    objective_text = (objective or "").strip()
    safety_level = classify_change_objective(objective_text)
    safety_notes: list[str] = []
    if safety_level == SafetyLevel.FORBIDDEN:
        safety_notes.append("Objective classified as FORBIDDEN by change safety policy")
    if classify_text(objective_text) == SafetyLevel.FORBIDDEN:
        safety_notes.append("Objective contains forbidden action vocabulary")

    repo_meta = refresh_repository_metadata(incremental=True)
    repo_report = repo_meta.get("report", {})
    graph = build_repository_graph(repo_report)
    investigation = investigate_objective(objective_text)
    investigation["graph"] = graph.to_dict()
    investigation["github"] = github_readonly_summary()
    if target_files:
        investigation["target_files"] = target_files
    investigation["modules"] = repo_report.get("modules", [])

    code_references: list[str] = []
    for module in repo_report.get("modules", [])[:10]:
        path = module.get("path", "")
        if path:
            code_references.append(path)
    for hit in (investigation.get("findings") or {}).values():
        if isinstance(hit, list):
            for item in hit[:3]:
                p = item.get("path", "") if isinstance(item, dict) else ""
                if p and p not in code_references:
                    code_references.append(p)

    production_evidence: list[dict[str, Any]] = []
    production_tool_outputs: list[dict[str, Any]] = []
    if include_production:
        try:
            evidence_items, tool_outputs, category, template_id, _, _ = collect_evidence(objective_text)
            production_evidence = _summarize_production_evidence(evidence_items, tool_outputs)
            production_tool_outputs = tool_outputs[:_ACW_READ_ONLY_COLLECTOR_LIMIT]
            investigation["production_category"] = category
            investigation["production_template_id"] = template_id
        except Exception as exc:
            logger.warning("acw evidence: production collection skipped: %s", exc)
            safety_notes.append(f"Production evidence collection skipped: {exc}")

    return {
        "objective": objective_text,
        "repository_context": {
            "modules_count": len(repo_report.get("modules", [])),
            "graph_nodes": len(graph.to_dict().get("nodes", [])),
            "report_summary": repo_report.get("summary", ""),
        },
        "code_references": code_references[:15],
        "investigation": investigation,
        "production_evidence": production_evidence,
        "production_tool_outputs": production_tool_outputs,
        "github_readonly": github_readonly_summary(),
        "safety_classification": {
            "level": safety_level.value if isinstance(safety_level, SafetyLevel) else str(safety_level),
            "notes": safety_notes,
        },
    }


def evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    """Compact summary for approval_package.json."""
    safety = evidence.get("safety_classification") or {}
    repo = evidence.get("repository_context") or {}
    return {
        "repository_modules": repo.get("modules_count", 0),
        "code_references": (evidence.get("code_references") or [])[:10],
        "production_evidence_count": len(evidence.get("production_evidence") or []),
        "safety_level": safety.get("level", ""),
        "safety_notes": safety.get("notes") or [],
    }
