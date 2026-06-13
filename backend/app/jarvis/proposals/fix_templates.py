"""Fix template registry for Jarvis Phase 4B patch proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FixTemplate:
    fix_template_id: str
    match: str
    target_files: list[str] = field(default_factory=list)
    test_paths: list[str] = field(default_factory=list)
    strategy: str = "template"
    no_fix_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "fix_template_id": self.fix_template_id,
            "match": self.match,
            "target_files": list(self.target_files),
            "test_paths": list(self.test_paths),
            "strategy": self.strategy,
            "no_fix_required": self.no_fix_required,
        }


FIX_TEMPLATES: tuple[FixTemplate, ...] = (
    FixTemplate(
        fix_template_id="orders.trigger_50001_cache_independent",
        match="Trigger order API failure blocks cache updates",
        target_files=[
            "backend/app/services/exchange_sync.py",
            "backend/app/services/unified_open_orders_fetch.py",
            "backend/tests/test_crypto_com_sync_status.py",
        ],
        test_paths=[
            "backend/tests/test_crypto_com_sync_status.py",
        ],
        strategy="template",
        no_fix_required=False,
    ),
)

_TEMPLATES_BY_ID: dict[str, FixTemplate] = {t.fix_template_id: t for t in FIX_TEMPLATES}
_TEMPLATES_BY_MATCH: dict[str, FixTemplate] = {t.match: t for t in FIX_TEMPLATES}


def list_fix_templates() -> list[dict[str, Any]]:
    return [t.to_dict() for t in FIX_TEMPLATES]


def get_fix_template(fix_template_id: str) -> dict[str, Any] | None:
    template = _TEMPLATES_BY_ID.get((fix_template_id or "").strip())
    return template.to_dict() if template else None


def find_fix_templates_for_root_cause(root_cause: str) -> list[dict[str, Any]]:
    """Return fix templates whose match string equals the investigation root cause."""
    normalized = (root_cause or "").strip()
    if not normalized:
        return []
    exact = _TEMPLATES_BY_MATCH.get(normalized)
    if exact:
        return [exact.to_dict()]
    return []
