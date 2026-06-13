"""Deterministic patch generation for Jarvis Phase 4B (no LLM)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.jarvis.proposals.fix_templates import get_fix_template
from app.jarvis.proposals.path_utils import resolve_repo_file, rewrite_patch_paths_for_workspace
from app.jarvis.proposals.template_matching import get_template_match

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
    "crypto.auth_40101_mismatch": [
        ("backend/scripts/diagnose_crypto_com_auth.py", "40101 usually means"),
        ("backend/scripts/diagnose_crypto_com_auth.py", "resolve_crypto_credentials"),
        ("backend/app/core/crypto_com_guardrail.py", "AUTH_40101_MESSAGE"),
    ],
    "dashboard.cache_db_mismatch": [
        ("backend/app/services/open_orders_resolver.py", "resolve_open_orders"),
        ("backend/app/api/routes_orders.py", "resolve_open_orders"),
        ("backend/app/services/open_orders_cache.py", "get_open_orders_cache"),
    ],
    "portfolio.equity_derived_fallback": [
        ("backend/app/services/portfolio_cache.py", "derived:collateral_minus_borrowed"),
        ("backend/app/services/portfolio_cache.py", "Exchange equity not found"),
    ],
    "websocket.same_origin_regression": [
        ("frontend/src/lib/priceStreamWsUrl.ts", "window.location.host"),
        ("frontend/src/lib/priceStreamWsUrl.ts", "isRejectedOverrideHostname"),
    ],
    "open_orders.stale_cache_fallback": [
        ("backend/app/services/open_orders_resolver.py", "stale_cache_db_fallback"),
        ("backend/app/services/open_orders_resolver.py", "ok_db_fallback"),
    ],
    "exchange_sync_blocked_by_order_history": [
        (
            "backend/app/services/exchange_sync.py",
            "sync_order_history now runs BEFORE sync_open_orders",
        ),
        ("backend/app/services/exchange_sync.py", "def sync_open_orders"),
    ],
    "telegram.bot_command_setup_failure": [
        ("backend/app/services/telegram_commands.py", "setMyCommands"),
        ("backend/app/services/telegram_commands.py", "_run_startup_diagnostics"),
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


def _noop_reason_for_template(fix_template_id: str) -> str:
    template = get_template_match(fix_template_id)
    if template and template.noop_reason:
        return template.noop_reason
    return "Fix already present in repository."


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
        reason = _noop_reason_for_template(fix_template_id)
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
