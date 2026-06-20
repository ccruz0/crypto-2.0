"""Structured recommendation generation for investigations.

Implements Deliverable 3 of jarvis_eval/SELF_HEALING_IMPROVEMENT_DESIGN.md.

Produces a RecommendationPlan with concrete files, commands, validation steps,
and risks, sourced from the fix-template catalog and from files actually seen in
collected evidence. A generic-phrase ban prevents non-actionable text from being
presented as a fix. Pure: no DB writes, no production access, no execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.jarvis.investigations.evidence_model import EvidenceItem

# Phrases that, on their own, do not constitute an actionable recommendation.
BANNED_PHRASES: tuple[str, ...] = (
    "review configuration",
    "check settings",
    "investigate further",
    "review collected evidence",
    "implement targeted fix",
    "no repair needed",
    "collect additional evidence",
    "needs further investigation",
    "requires further investigation",
)


@dataclass
class RecommendationPlan:
    proposed_fix: str
    affected_files: list[str] = field(default_factory=list)
    commands: list[dict[str, str]] = field(default_factory=list)
    validation_steps: list[str] = field(default_factory=list)
    risks: list[dict[str, str]] = field(default_factory=list)
    rollback: str = ""
    specificity: float = 0.1

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposed_fix": self.proposed_fix,
            "affected_files": list(self.affected_files),
            "commands": list(self.commands),
            "validation_steps": list(self.validation_steps),
            "risks": list(self.risks),
            "rollback": self.rollback,
            "specificity": round(self.specificity, 2),
        }


def is_generic_recommendation(text: str) -> bool:
    """True when the text reduces to banned, non-actionable phrasing."""
    low = (text or "").strip().lower()
    if not low:
        return True
    return any(phrase in low for phrase in BANNED_PHRASES)


def _salient_keyword(cause: str) -> str:
    tokens = [t for t in re.split(r"[^A-Za-z0-9_]+", cause or "") if len(t) >= 5]
    return tokens[0] if tokens else ""


def _inspect_command(file_path: str, keyword: str) -> dict[str, str]:
    if keyword:
        return {
            "description": f"Inspect {file_path} for '{keyword}'",
            "command": f"grep -n -i '{keyword}' {file_path}",
        }
    return {
        "description": f"Inspect {file_path}",
        "command": f"sed -n '1,120p' {file_path}",
    }


def _match_fix_template(root_cause: str, category: str):
    """Lazily match a FixTemplate for the root cause (avoids import cycles)."""
    try:
        from app.jarvis.proposals.template_matching import (
            get_template_match,
            match_templates_for_investigation,
        )
    except Exception:
        return None
    try:
        result = match_templates_for_investigation(
            {"root_cause": root_cause, "category": category}
        )
        if result.primary_template:
            return get_template_match(result.primary_template)
    except Exception:
        return None
    return None


def _evidence_file_paths(evidence: list[EvidenceItem]) -> list[str]:
    paths: list[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        fp = item.get("file_path")
        if fp and fp not in paths:
            paths.append(str(fp))
    return paths[:5]


def _ops_scope_markers(text: str) -> bool:
    low = (text or "").lower()
    return any(
        marker in low
        for marker in (
            "restart ",
            "market-updater",
            "docker compose",
            "service and verify",
            "inspect container",
        )
    )


def _frontend_scope_files(files: list[str]) -> bool:
    cleaned = [f.replace(" (candidate)", "") for f in files]
    return bool(cleaned) and all(f.startswith("frontend/") for f in cleaned)


def _fix_scope_mismatch(
    target_files: list[str],
    existing_fix: str,
    template_recommended_fix: str,
) -> bool:
    """True when template file scope disagrees with the proposed operational fix text."""
    if not target_files:
        return False
    fix_blob = f"{existing_fix} {template_recommended_fix}".lower()
    if _frontend_scope_files(target_files) and _ops_scope_markers(fix_blob):
        return True
    if _frontend_scope_files(target_files) and "backend/" in fix_blob and "frontend" not in existing_fix.lower():
        return True
    return False


def _evidence_supports_template_scope(
    *,
    target_files: list[str],
    evidence: list[EvidenceItem],
    existing_fix: str,
    template_recommended_fix: str,
) -> bool:
    """Catalog files alone cannot justify full specificity without corroborating evidence."""
    if _fix_scope_mismatch(target_files, existing_fix, template_recommended_fix):
        return False
    evidence_paths = _evidence_file_paths(evidence)
    if evidence_paths and any(
        any(tp in ep or ep.endswith(tp.split("/")[-1]) for tp in target_files) for ep in evidence_paths
    ):
        return True
    template_keywords = tuple(
        kw.lower()
        for kw in (
            "equity",
            "websocket",
            "open_orders",
            "cache",
            "portfolio",
            "runtime.env",
            "40101",
        )
    )
    for item in evidence:
        detail = (item.get("detail") or "").lower()
        if any(kw in detail for kw in template_keywords):
            if item.get("is_direct") or str(item.get("confidence")) == "high":
                return True
    if existing_fix and not is_generic_recommendation(existing_fix):
        fix_low = existing_fix.lower()
        if any(kw in fix_low for kw in template_keywords):
            return True
    return False


def build_recommendation_plan(
    *,
    root_cause: str | None,
    category: str = "",
    evidence: list[EvidenceItem] | None = None,
    existing_fix: str = "",
    existing_verification: list[str] | None = None,
) -> RecommendationPlan:
    """Build a structured, concrete recommendation for a root cause.

    Priority: (1) template-backed concrete plan, (2) evidence-derived candidate
    files, (3) explicit gap statement when only generic content is available.
    """
    evidence = evidence or []
    existing_verification = list(existing_verification or [])
    keyword = _salient_keyword(root_cause or "")

    # (1) Template-backed: concrete files, commands, validation from the catalog.
    template = _match_fix_template(root_cause, category) if root_cause else None
    if template is not None and template.target_files:
        files = list(template.target_files)
        commands = [_inspect_command(f, keyword) for f in files[:5]]
        for test_path in template.test_paths:
            commands.append(
                {"description": f"Run regression test {test_path}", "command": f"pytest {test_path}"}
            )
        validation_steps = list(template.validation_rules) + [
            f"pytest {tp}" for tp in template.test_paths
        ]
        risks = [
            {
                "description": f"Change touches {len(files)} file(s) ({', '.join(files[:3])}).",
                "severity": template.risk_level,
                "mitigation": "Apply behind sandbox + two human approval gates (ACW); no auto-merge/deploy.",
            }
        ]
        fix = existing_fix if (existing_fix and not is_generic_recommendation(existing_fix)) else (
            template.recommended_fix or (root_cause or "")
        )
        scope_supported = _evidence_supports_template_scope(
            target_files=files,
            evidence=evidence,
            existing_fix=fix,
            template_recommended_fix=template.recommended_fix or "",
        )
        if _fix_scope_mismatch(files, fix, template.recommended_fix or ""):
            specificity = 0.5
        elif scope_supported and files and validation_steps:
            specificity = 1.0
        else:
            specificity = 0.5
        return RecommendationPlan(
            proposed_fix=fix,
            affected_files=files,
            commands=commands,
            validation_steps=validation_steps,
            risks=risks,
            rollback="Revert the patch via the approved rollback path and re-run the investigation.",
            specificity=specificity,
        )

    # (2) Evidence-derived candidate files (only files actually seen in evidence).
    repo_files = _evidence_file_paths(evidence)
    if repo_files and existing_fix and not is_generic_recommendation(existing_fix):
        commands = [_inspect_command(f, keyword) for f in repo_files]
        validation_steps = existing_verification or [
            f"Re-run the investigation and confirm '{(root_cause or '')[:60]}' is resolved."
        ]
        risks = [
            {
                "description": "Affected files are inferred from collected evidence and must be confirmed.",
                "severity": "medium",
                "mitigation": "Treat files as candidates; require human review before any edit.",
            }
        ]
        return RecommendationPlan(
            proposed_fix=existing_fix,
            affected_files=[f"{f} (candidate)" for f in repo_files],
            commands=commands,
            validation_steps=validation_steps,
            risks=risks,
            rollback="Revert and re-run the investigation.",
            specificity=0.5,
        )

    # (3) Generic-only -> explicit gap statement; never present banned-only text as a fix.
    missing = "concrete file/command evidence"
    gap = (
        f"Insufficient evidence to produce a concrete fix; missing: {missing} "
        f"for '{(root_cause or 'unknown root cause')[:80]}'."
    )
    return RecommendationPlan(
        proposed_fix=gap,
        affected_files=[],
        commands=[],
        validation_steps=[],
        risks=[
            {
                "description": "No actionable fix could be derived from current evidence.",
                "severity": "low",
                "mitigation": "Gather domain evidence (database, logs, exchange, repository) and re-run.",
            }
        ],
        rollback="",
        specificity=0.1,
    )
