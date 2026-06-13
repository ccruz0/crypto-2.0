"""Deterministic patch generation for Jarvis Phase 4B (no LLM)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.jarvis.proposals.fix_templates import get_fix_template
from app.jarvis.proposals.path_utils import resolve_repo_file, rewrite_patch_paths_for_workspace

_DATA_DIR = Path(__file__).resolve().parent / "data"

_FIX_PRESENT_MARKERS: dict[str, list[tuple[str, str]]] = {
    "orders.trigger_50001_cache_independent": [
        (
            "backend/app/services/unified_open_orders_fetch.py",
            "Trigger orders failure (e.g. 50001) is non-fatal",
        ),
        (
            "backend/app/services/exchange_sync.py",
            "fetch_unified_open_orders",
        ),
        (
            "backend/tests/test_crypto_com_sync_status.py",
            "test_fetch_unified_open_orders_regular_ok_trigger_50001_non_fatal",
        ),
    ],
}

_PATCH_FILES: dict[str, str] = {
    "orders.trigger_50001_cache_independent": "orders_trigger_50001_cache_independent.patch",
}


@dataclass
class PatchGenerationResult:
    fix_template_id: str
    patch_content: str
    is_noop: bool = False
    fix_already_present: bool = False
    files_affected: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fix_template_id": self.fix_template_id,
            "is_noop": self.is_noop,
            "fix_already_present": self.fix_already_present,
            "files_affected": list(self.files_affected),
            "reason": self.reason,
            "patch_bytes": len(self.patch_content.encode("utf-8")),
        }


def is_fix_already_present(repo_root: Path, fix_template_id: str) -> bool:
    """Return True when all marker strings for the template exist in the repo."""
    markers = _FIX_PRESENT_MARKERS.get(fix_template_id)
    if not markers:
        return False
    for rel_path, marker in markers:
        path = resolve_repo_file(repo_root, rel_path)
        if path is None:
            return False
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return False
        if marker not in content:
            return False
    return True


def _noop_patch_content(fix_template_id: str, *, reason: str) -> str:
    return (
        f"# Phase 4B no-op proposal\n"
        f"# Fix template: {fix_template_id}\n"
        f"# Status: fix already present in repository — no patch application required.\n"
        f"#\n"
        f"# {reason}\n"
    )


def _load_canonical_patch(fix_template_id: str) -> str:
    filename = _PATCH_FILES.get(fix_template_id)
    if not filename:
        raise ValueError(f"no canonical patch file for template: {fix_template_id}")
    path = _DATA_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"canonical patch missing: {path}")
    return path.read_text(encoding="utf-8")


def generate_patch_for_template(
    fix_template_id: str,
    *,
    repo_root: Path,
) -> PatchGenerationResult:
    """Generate a deterministic patch for a known fix template."""
    template = get_fix_template(fix_template_id)
    if template is None:
        raise ValueError(f"unknown fix template: {fix_template_id}")

    target_files = list(template.get("target_files") or [])

    if is_fix_already_present(repo_root, fix_template_id):
        reason = (
            "The trigger-order 50001 cache-independent fetch path is already implemented "
            "in the repository."
        )
        return PatchGenerationResult(
            fix_template_id=fix_template_id,
            patch_content=_noop_patch_content(fix_template_id, reason=reason),
            is_noop=True,
            fix_already_present=True,
            files_affected=target_files,
            reason=reason,
        )

    patch_content = _load_canonical_patch(fix_template_id)
    patch_content = rewrite_patch_paths_for_workspace(patch_content, repo_root)
    return PatchGenerationResult(
        fix_template_id=fix_template_id,
        patch_content=patch_content,
        is_noop=False,
        fix_already_present=False,
        files_affected=target_files,
        reason="Canonical template patch generated for pre-fix repository state.",
    )
