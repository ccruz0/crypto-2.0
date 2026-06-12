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
