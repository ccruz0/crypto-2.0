"""Safety classification for Jarvis task execution (SAFE_AUTO / NEEDS_APPROVAL / FORBIDDEN)."""

from __future__ import annotations

import re
from enum import Enum


class SafetyLevel(str, Enum):
    SAFE_AUTO = "safe_auto"
    NEEDS_APPROVAL = "needs_approval"
    FORBIDDEN = "forbidden"


_FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\btrade\b",
        r"\bexecute\s+order\b",
        r"\bdeploy\b",
        r"\bdelete\b",
        r"\bterminate\b",
        r"\bmodify\b.*\bsecret",
        r"\bchange\b.*\bsecret",
        r"\bwrite\b.*\b(file|secret|env|database)\b",
        r"\bchange\b.*\bsecret",
        r"\bshell\b.*\bexec",
        r"\brm\s+-rf\b",
    )
)

_NEEDS_APPROVAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\brestart\b",
        r"\bconfig\s+change\b",
        r"\benv\s+change\b",
        r"\bnginx\b.*\b(change|update|config)\b",
        r"\bchange\b.*\bnginx\b",
        r"\bdeploy\b",
        r"\bwrite\b",
        r"\bmutate\b",
    )
)

_READ_ONLY_TOOL_ACTIONS: frozenset[str] = frozenset(
    {
        "read_logs",
        "inspect_container",
        "inspect_repository",
        "inspect_runtime",
        "inspect_health",
        "inspect_costs",
        "gather_logs",
        "analyze_failure",
        "identify_root_cause",
        "recommend_fix",
        "search_repository",
        "inspect_code",
        "summarize_architecture",
        "summarize_modules",
    }
)


def classify_text(text: str) -> SafetyLevel:
    normalized = (text or "").strip()
    if not normalized:
        return SafetyLevel.SAFE_AUTO
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(normalized):
            return SafetyLevel.FORBIDDEN
    for pattern in _NEEDS_APPROVAL_PATTERNS:
        if pattern.search(normalized):
            return SafetyLevel.NEEDS_APPROVAL
    return SafetyLevel.SAFE_AUTO


def classify_action(action: str) -> SafetyLevel:
    key = (action or "").strip().lower()
    if key in _READ_ONLY_TOOL_ACTIONS:
        return SafetyLevel.SAFE_AUTO
    return classify_text(key.replace("_", " "))


def merge_safety_levels(*levels: SafetyLevel) -> SafetyLevel:
    if SafetyLevel.FORBIDDEN in levels:
        return SafetyLevel.FORBIDDEN
    if SafetyLevel.NEEDS_APPROVAL in levels:
        return SafetyLevel.NEEDS_APPROVAL
    return SafetyLevel.SAFE_AUTO


def approval_required_for_level(level: SafetyLevel) -> bool:
    return level == SafetyLevel.NEEDS_APPROVAL


def is_forbidden(level: SafetyLevel) -> bool:
    return level == SafetyLevel.FORBIDDEN


# Phase 4/5 action classifications (patch/PR/deploy/trading/secrets).
PHASE4_ACTION_CLASSIFICATION: dict[str, SafetyLevel] = {
    "patch_generation": SafetyLevel.SAFE_AUTO,
    "patch_application": SafetyLevel.NEEDS_APPROVAL,
    "pr_creation": SafetyLevel.NEEDS_APPROVAL,
    "merge": SafetyLevel.FORBIDDEN,
    "deploy": SafetyLevel.FORBIDDEN,
    "trading": SafetyLevel.FORBIDDEN,
    "secrets_access": SafetyLevel.FORBIDDEN,
    "repository_scan": SafetyLevel.SAFE_AUTO,
    "code_review": SafetyLevel.SAFE_AUTO,
    "test_execution": SafetyLevel.SAFE_AUTO,
    "github_read": SafetyLevel.SAFE_AUTO,
    "test_selection": SafetyLevel.SAFE_AUTO,
}

# Phase 5 extended classifications.
PHASE5_ACTION_CLASSIFICATION: dict[str, SafetyLevel] = {
    **PHASE4_ACTION_CLASSIFICATION,
    "create_branch": SafetyLevel.NEEDS_APPROVAL,
    "apply_patch": SafetyLevel.NEEDS_APPROVAL,
    "run_write_git": SafetyLevel.NEEDS_APPROVAL,
    "create_pr": SafetyLevel.NEEDS_APPROVAL,
    "update_pr": SafetyLevel.NEEDS_APPROVAL,
    "push_to_main": SafetyLevel.FORBIDDEN,
    "force_push": SafetyLevel.FORBIDDEN,
    "delete_branch": SafetyLevel.FORBIDDEN,
    "close_pr": SafetyLevel.FORBIDDEN,
    "database_destructive_write": SafetyLevel.FORBIDDEN,
    "volume_deletion": SafetyLevel.FORBIDDEN,
    "disable_security": SafetyLevel.FORBIDDEN,
    "expose_openclaw": SafetyLevel.FORBIDDEN,
}


def classify_change_objective(text: str) -> SafetyLevel:
    """Phase 4 change workflow: patch generation objectives stay SAFE unless clearly forbidden."""
    normalized = (text or "").strip()
    if not normalized:
        return SafetyLevel.SAFE_AUTO
    change_forbidden = (
        r"\btrade\b",
        r"\bexecute\s+order\b",
        r"\bmerge\b",
        r"\bdelete\b",
        r"\bterminate\b",
        r"\bmodify\b.*\bsecret",
        r"\bchange\b.*\bsecret",
        r"\brm\s+-rf\b",
        r"\bdeploy\s+to\s+(prod|production)\b",
        r"\bwrite\b.*\b(file|secret|env|database)\b",
    )
    for pattern in change_forbidden:
        if re.search(pattern, normalized, re.IGNORECASE):
            return SafetyLevel.FORBIDDEN
    return SafetyLevel.SAFE_AUTO


def classify_phase4_action(action: str) -> SafetyLevel:
    key = (action or "").strip().lower()
    if key in PHASE4_ACTION_CLASSIFICATION:
        return PHASE4_ACTION_CLASSIFICATION[key]
    return classify_action(key)


def classify_phase5_action(action: str) -> SafetyLevel:
    """Phase 5 change execution safety classification."""
    key = (action or "").strip().lower()
    if key in PHASE5_ACTION_CLASSIFICATION:
        return PHASE5_ACTION_CLASSIFICATION[key]
    return classify_phase4_action(key)
