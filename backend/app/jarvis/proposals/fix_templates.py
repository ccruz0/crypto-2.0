"""Fix template registry for Jarvis Phase 4B patch proposals."""

from __future__ import annotations

from typing import Any

from app.jarvis.proposals.template_catalog import FIX_TEMPLATES, FixTemplate
from app.jarvis.proposals.template_matching import (
    find_fix_templates_for_root_cause,
    get_template_match,
    match_templates_for_investigation,
)

__all__ = [
    "FIX_TEMPLATES",
    "FixTemplate",
    "find_fix_templates_for_root_cause",
    "get_fix_template",
    "get_fix_template_detail",
    "list_fix_template_summaries",
    "list_fix_templates",
    "match_templates_for_investigation",
]


def list_fix_templates() -> list[dict[str, Any]]:
    return [template.to_dict() for template in FIX_TEMPLATES]


def list_fix_template_summaries() -> list[dict[str, Any]]:
    return [template.to_summary_dict() for template in FIX_TEMPLATES]


def get_fix_template(fix_template_id: str) -> dict[str, Any] | None:
    template = get_template_match(fix_template_id)
    return template.to_dict() if template else None


def get_fix_template_detail(fix_template_id: str) -> dict[str, Any] | None:
    template = get_template_match(fix_template_id)
    return template.to_dict(include_full=True) if template else None
