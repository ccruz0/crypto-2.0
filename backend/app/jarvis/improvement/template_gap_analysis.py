"""Detect investigation template gaps and generate improvement recommendations."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from app.jarvis.investigations.investigation_types import INVESTIGATION_TEMPLATES, InvestigationStatus

_INSUFFICIENT_EVIDENCE_THRESHOLD_PCT = 25.0
_GENERIC_OVERUSE_THRESHOLD_PCT = 20.0
_MIN_INVESTIGATIONS_FOR_GAP = 2

_KNOWN_TEMPLATE_IDS = {t.template_id for t in INVESTIGATION_TEMPLATES} | {"generic"}
_KNOWN_CATEGORIES = {t.category for t in INVESTIGATION_TEMPLATES}


def _objective_keywords(objective: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", objective.lower())
    return {w for w in words if len(w) >= 4}


def analyze_template_gaps(
    investigations: list[dict[str, Any]],
    template_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Identify template coverage gaps and produce gap records + raw recommendations."""
    gaps: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    total = len(investigations)
    generic_count = sum(1 for r in investigations if str(r.get("template_id") or "generic") == "generic")
    generic_pct = round(generic_count / total * 100, 1) if total else 0.0

    # High insufficient_evidence rate templates
    for tmpl in template_metrics:
        template_id = tmpl["template_id"]
        inv_count = int(tmpl["investigations"])
        insuff_rate = float(tmpl["insufficient_evidence_rate_pct"])
        insuff_count = int(tmpl["insufficient_evidence"])

        if inv_count >= _MIN_INVESTIGATIONS_FOR_GAP and insuff_rate >= _INSUFFICIENT_EVIDENCE_THRESHOLD_PCT:
            gaps.append(
                {
                    "gap_type": "high_insufficient_evidence",
                    "template_id": template_id,
                    "investigations": inv_count,
                    "insufficient_evidence": insuff_count,
                    "insufficient_evidence_rate_pct": insuff_rate,
                    "severity": "high" if insuff_rate >= 40 else "medium",
                }
            )
            recommendations.append(
                {
                    "id": f"template-insuff-{template_id}",
                    "category": "template_gap",
                    "impact": "high" if insuff_rate >= 40 else "medium",
                    "frequency": insuff_count,
                    "confidence": min(95.0, 50.0 + insuff_rate),
                    "title": f"Improve evidence collectors for '{template_id}' template",
                    "recommendation": (
                        f"Template '{template_id}' has {insuff_rate:.0f}% insufficient_evidence rate "
                        f"({insuff_count}/{inv_count} investigations). Add mandatory collectors or "
                        f"expand log/search coverage."
                    ),
                    "reason": f"High insufficient_evidence rate ({insuff_rate:.1f}%)",
                    "evidence": [
                        f"{inv_count} investigations used template '{template_id}'",
                        f"{insuff_count} ended with insufficient_evidence",
                        f"Rate: {insuff_rate:.1f}% (threshold: {_INSUFFICIENT_EVIDENCE_THRESHOLD_PCT}%)",
                    ],
                    "expected_benefit": f"Reduce insufficient_evidence by ~{min(30, int(insuff_rate * 0.5))}%",
                }
            )

    # Generic template overuse
    if total >= 3 and generic_pct >= _GENERIC_OVERUSE_THRESHOLD_PCT:
        generic_objectives = [
            str(r.get("objective") or "")
            for r in investigations
            if str(r.get("template_id") or "generic") == "generic"
        ]
        keyword_counter: Counter[str] = Counter()
        for obj in generic_objectives:
            keyword_counter.update(_objective_keywords(obj))

        top_keywords = [kw for kw, _ in keyword_counter.most_common(3)]
        keyword_hint = ", ".join(top_keywords) if top_keywords else "specialized objectives"

        gaps.append(
            {
                "gap_type": "generic_overuse",
                "template_id": "generic",
                "investigations": generic_count,
                "generic_rate_pct": generic_pct,
                "top_keywords": top_keywords,
                "severity": "high" if generic_pct >= 35 else "medium",
            }
        )
        recommendations.append(
            {
                "id": "template-generic-overuse",
                "category": "template_gap",
                "impact": "high" if generic_pct >= 35 else "medium",
                "frequency": generic_count,
                "confidence": min(90.0, 40.0 + generic_pct),
                "title": "Create dedicated templates for frequently generic objectives",
                "recommendation": (
                    f"{generic_pct:.0f}% of investigations ({generic_count}/{total}) fall into the "
                    f"generic template. Common themes: {keyword_hint}. "
                    f"Create dedicated templates for recurring objective patterns."
                ),
                "reason": f"Generic template overuse ({generic_pct:.1f}%)",
                "evidence": [
                    f"{generic_count} of {total} investigations used generic template",
                    f"Generic rate: {generic_pct:.1f}% (threshold: {_GENERIC_OVERUSE_THRESHOLD_PCT}%)",
                    f"Common keywords: {keyword_hint}",
                ],
                "expected_benefit": "Improve investigation accuracy and reduce false positives by 20–30%",
            }
        )

    # Missing investigation categories
    category_counts: Counter[str] = Counter()
    for row in investigations:
        cat = str(row.get("category") or "unknown").strip().lower()
        if cat:
            category_counts[cat] += 1

    template_categories = _KNOWN_CATEGORIES
    for category, count in category_counts.items():
        if category not in template_categories and count >= _MIN_INVESTIGATIONS_FOR_GAP:
            gaps.append(
                {
                    "gap_type": "missing_category",
                    "category": category,
                    "investigations": count,
                    "severity": "medium",
                }
            )
            recommendations.append(
                {
                    "id": f"template-missing-cat-{category}",
                    "category": "template_gap",
                    "impact": "medium",
                    "frequency": count,
                    "confidence": 70.0,
                    "title": f"Create investigation template for '{category}' category",
                    "recommendation": (
                        f"Category '{category}' has {count} investigations but no dedicated "
                        f"investigation template. Add a template with targeted collectors."
                    ),
                    "reason": f"Missing template for category '{category}'",
                    "evidence": [
                        f"{count} investigations tagged as category '{category}'",
                        f"No matching template in catalog ({', '.join(sorted(template_categories))})",
                    ],
                    "expected_benefit": "Faster root-cause identification for this incident class",
                }
            )

    # Trigger-order / Crypto.com specific gap (common production pattern)
    trigger_pattern = re.compile(r"trigger|50001|crypto\.?com", re.IGNORECASE)
    trigger_rows = [
        r for r in investigations
        if trigger_pattern.search(str(r.get("objective") or "") + " " + str(r.get("root_cause") or ""))
    ]
    if len(trigger_rows) >= 2:
        trigger_templates = Counter(str(r.get("template_id") or "generic") for r in trigger_rows)
        if trigger_templates.get("generic", 0) >= 1 or "open_orders_empty" in trigger_templates:
            gaps.append(
                {
                    "gap_type": "specialized_trigger_orders",
                    "investigations": len(trigger_rows),
                    "templates_used": dict(trigger_templates),
                    "severity": "high",
                }
            )
            recommendations.append(
                {
                    "id": "template-trigger-order-dedicated",
                    "category": "template_gap",
                    "impact": "high",
                    "frequency": len(trigger_rows),
                    "confidence": 85.0,
                    "title": "Create dedicated template for Crypto.com trigger-order failures",
                    "recommendation": (
                        "Trigger-order and Crypto.com API failures recur frequently. "
                        "Create a dedicated advanced-order collector template with "
                        "reconcile_crypto_com_open_orders and trigger-specific log patterns."
                    ),
                    "reason": f"{len(trigger_rows)} trigger-order related investigations detected",
                    "evidence": [
                        f"{len(trigger_rows)} investigations mention trigger orders or Crypto.com",
                        f"Templates used: {dict(trigger_templates)}",
                    ],
                    "expected_benefit": "Reduce false positives by ~30% on order mismatch investigations",
                }
            )

    # Templates with high failure rates
    for tmpl in template_metrics:
        fail_rate = float(tmpl["failure_rate_pct"])
        inv_count = int(tmpl["investigations"])
        if inv_count >= _MIN_INVESTIGATIONS_FOR_GAP and fail_rate >= 30:
            template_id = tmpl["template_id"]
            gaps.append(
                {
                    "gap_type": "high_failure_rate",
                    "template_id": template_id,
                    "investigations": inv_count,
                    "failure_rate_pct": fail_rate,
                    "severity": "high" if fail_rate >= 50 else "medium",
                }
            )

    return {
        "gaps": gaps,
        "recommendations": recommendations,
        "summary": {
            "total_gaps": len(gaps),
            "generic_rate_pct": generic_pct,
            "generic_investigations": generic_count,
            "known_templates": sorted(_KNOWN_TEMPLATE_IDS),
        },
    }
