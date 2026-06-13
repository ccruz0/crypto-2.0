"""Template matching and confidence scoring for Jarvis Phase 4B."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.jarvis.proposals.template_catalog import FIX_TEMPLATES, FixTemplate

_EXACT_MATCH_SCORE = 100
_PATTERN_MATCH_SCORE = 18
_RECOMMENDED_FIX_MATCH_SCORE = 12
_CATEGORY_MATCH_SCORE = 8
_MIN_CANDIDATE_SCORE = 25
_AMBIGUITY_GAP = 10

_COMPILED_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    template.fix_template_id: tuple(
        re.compile(pattern, re.IGNORECASE) for pattern in template.match_patterns
    )
    for template in FIX_TEMPLATES
}


@dataclass
class TemplateMatch:
    fix_template_id: str
    score: int
    template_confidence: float
    matched_patterns: list[str] = field(default_factory=list)
    match_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        template = _TEMPLATE_BY_ID[self.fix_template_id]
        payload = template.to_dict()
        payload.update(
            {
                "score": self.score,
                "template_confidence": self.template_confidence,
                "matched_patterns": list(self.matched_patterns),
                "match_reasons": list(self.match_reasons),
            }
        )
        return payload


@dataclass
class TemplateMatchResult:
    primary_template: str | None
    score: int
    template_confidence: float
    matches: list[TemplateMatch] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fix_template_candidates(self) -> list[dict[str, Any]]:
        return [match.to_dict() for match in self.matches]

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_template": self.primary_template,
            "score": self.score,
            "template_confidence": self.template_confidence,
            "alternatives": list(self.alternatives),
            "fix_template_candidates": self.fix_template_candidates,
        }


_TEMPLATE_BY_ID: dict[str, FixTemplate] = {t.fix_template_id: t for t in FIX_TEMPLATES}


def _normalize(text: str | None) -> str:
    return (text or "").strip()


def _search_blob(*parts: str | None) -> str:
    return " ".join(_normalize(part) for part in parts if _normalize(part))


def _score_template(
    template: FixTemplate,
    *,
    root_cause: str,
    recommended_fix: str,
    summary: str,
    category: str,
    objective: str,
) -> TemplateMatch:
    score = 0
    matched_patterns: list[str] = []
    match_reasons: list[str] = []

    if template.root_cause_exact and root_cause == template.root_cause_exact:
        score += _EXACT_MATCH_SCORE
        match_reasons.append("exact_root_cause")

    root_blob = root_cause
    context_blob = _search_blob(summary, objective)
    root_pattern_hits = 0
    for pattern, compiled in zip(template.match_patterns, _COMPILED_PATTERNS[template.fix_template_id]):
        if compiled.search(root_blob):
            score += _PATTERN_MATCH_SCORE
            root_pattern_hits += 1
            matched_patterns.append(pattern)
            match_reasons.append(f"root_cause_pattern:{pattern}")

    for pattern, compiled in zip(template.match_patterns, _COMPILED_PATTERNS[template.fix_template_id]):
        if compiled.search(context_blob) and pattern not in matched_patterns:
            score += _PATTERN_MATCH_SCORE // 2
            matched_patterns.append(pattern)
            match_reasons.append(f"context_pattern:{pattern}")

    if score > 0 and root_pattern_hits == 0 and "exact_root_cause" not in match_reasons:
        # Ancillary signals alone must not qualify a template.
        score = 0
        matched_patterns.clear()
        match_reasons.clear()
        return TemplateMatch(
            fix_template_id=template.fix_template_id,
            score=0,
            template_confidence=0.0,
        )

    if recommended_fix:
        fix_tokens = [
            word
            for word in re.split(r"[^a-z0-9]+", template.recommended_fix.lower())
            if len(word) >= 5
        ][:6]
        if any(token in recommended_fix.lower() for token in fix_tokens):
            score += _RECOMMENDED_FIX_MATCH_SCORE
            match_reasons.append("recommended_fix_overlap")

    if category:
        for supported in template.supported_investigations:
            if supported.lower() in category.lower() or category.lower() in supported.lower():
                score += _CATEGORY_MATCH_SCORE
                match_reasons.append(f"category:{supported}")
                break

    template_confidence = float(min(score, 100))
    return TemplateMatch(
        fix_template_id=template.fix_template_id,
        score=score,
        template_confidence=template_confidence,
        matched_patterns=matched_patterns,
        match_reasons=match_reasons,
    )


def match_templates_for_investigation(
    investigation: dict[str, Any],
    *,
    min_score: int = _MIN_CANDIDATE_SCORE,
) -> TemplateMatchResult:
    """Rank fix templates against an investigation's root cause and supporting text."""
    root_cause = _normalize(investigation.get("root_cause"))
    recommended_fix = _normalize(investigation.get("recommended_fix"))
    summary = _normalize(investigation.get("summary"))
    category = _normalize(investigation.get("category"))
    objective = _normalize(investigation.get("objective"))

    if not root_cause and not summary and not objective:
        return TemplateMatchResult(
            primary_template=None,
            score=0,
            template_confidence=0.0,
        )

    scored = [
        _score_template(
            template,
            root_cause=root_cause,
            recommended_fix=recommended_fix,
            summary=summary,
            category=category,
            objective=objective,
        )
        for template in FIX_TEMPLATES
    ]
    scored.sort(key=lambda item: (-item.score, item.fix_template_id))
    matches = [item for item in scored if item.score >= min_score]

    if not matches:
        return TemplateMatchResult(
            primary_template=None,
            score=0,
            template_confidence=0.0,
        )

    primary = matches[0]
    alternatives = [
        {
            "fix_template_id": alt.fix_template_id,
            "score": alt.score,
            "template_confidence": alt.template_confidence,
            "matched_patterns": list(alt.matched_patterns),
        }
        for alt in matches[1:]
        if primary.score - alt.score <= _AMBIGUITY_GAP
    ]

    return TemplateMatchResult(
        primary_template=primary.fix_template_id,
        score=primary.score,
        template_confidence=primary.template_confidence,
        matches=matches,
        alternatives=alternatives,
    )


def find_fix_templates_for_root_cause(root_cause: str) -> list[dict[str, Any]]:
    """Backward-compatible lookup ranked by match score."""
    result = match_templates_for_investigation({"root_cause": root_cause})
    return result.fix_template_candidates


def get_template_match(template_id: str) -> FixTemplate | None:
    return _TEMPLATE_BY_ID.get((template_id or "").strip())
