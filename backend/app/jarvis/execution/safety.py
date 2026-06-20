"""Safety classification for Jarvis task execution (SAFE_AUTO / NEEDS_APPROVAL / FORBIDDEN)."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any


class SafetyLevel(str, Enum):
    SAFE_AUTO = "safe_auto"
    NEEDS_APPROVAL = "needs_approval"
    FORBIDDEN = "forbidden"


# Read-only investigation objectives must not be blocked by trading vocabulary alone.
_INVESTIGATION_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(investigate|diagnose|explain|why|compare|reconcile|audit|check|review|analyze|analyse|find\s+out|look\s+into)\b",
        r"\b(missing|not\s+(?:visible|showing|matching)|mismatch|discrepancy|different|incorrect|wrong)\b",
        r"\b(open|executed|wallet|portfolio)\s+orders?\b",
        r"\borders?\b.*\b(missing|not\s+(?:visible|showing)|mismatch|discrepancy|different)\b",
        r"\bportfolio\s+reconciliation\b",
        r"\bcrypto\.?com\b.*\b(dashboard|differ|compare|reconcile|missing)\b",
        r"\bdashboard\b.*\b(missing|not\s+(?:visible|showing)|differ|mismatch)\b",
    )
)

# Explicit read-only investigation guards — checked before destructive patterns.
_READ_ONLY_INVESTIGATION_GUARDS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwithout\s+placing\s+trades?\b",
        r"\bread[\s-]only\b",
        r"\bno\s+trading\b",
        r"\bdo\s+not\s+(trade|place|execute)\b",
        r"\bdon'?t\s+(trade|place|execute)\b",
    )
)

# Explicit safety constraints — negated dangerous actions must not trigger FORBIDDEN.
_READ_ONLY_SAFETY_GUARDS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bdo\s+not\s+(deploy|modify|delete|merge|create|push|write|patch|terminate)\b",
        r"\bdon'?t\s+(deploy|modify|delete|merge|create|push|write|patch|terminate)\b",
        r"\bnever\s+(deploy|modify|delete|merge|create|push|write|patch|terminate)\b",
        r"\bwithout\s+(deploying|modifying|deleting|merging|creating|pushing|writing)\b",
        r"\bno\s+(deploy(?:ment)?|merges?|patches?|prs?|pull\s+requests?)\b",
        r"\breport\s+only\b",
        r"\bdo\s+not\s+create\s+(?:any\s+)?(?:prs?|pull\s+requests?|patches?)\b",
    )
)

# Negation immediately before a matched dangerous token (lookback within prefix window).
_NEGATION_BEFORE_ACTION_RE = re.compile(
    r"(?:\bdo\s+not\b|\bdon'?t\b|\bnever\b|\bwithout\b|\bnot\b|\bno\b)(?:\s+\w+){0,4}\s*$",
    re.IGNORECASE,
)

# Trading/write/destructive intent — forbidden even when mixed with investigation wording.
_DESTRUCTIVE_INVESTIGATION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(execute|place|submit)\b.*\b(trade|order|market\s+order)\b",
        r"\b(place|submit)\b.*\b(replacement\s+)?orders?\b",
        r"\bcancel\b.*\b(?:all\s+)?(?:open\s+)?orders?\b",
        r"\bmarket\s+order\b",
        r"\b(buy|sell)\s+(?!orders?\b)(?:BTC|ETH|[A-Z]{2,10}|\w+)\b",
        r"\band\s+(buy|sell)\b",
        r"\b(close|open)\b.*\bpositions?\b",
        r"\bclose\s+all\s+positions?\b",
        r"\b(delete|terminate|drop|truncate|purge|wipe)\b.*\b(resources?|buckets?|databases?|db|volumes?|orders?)\b",
        r"\b(modify|change|rotate|update)\b.*\b(secrets?|credentials?|password|api\s+keys?)\b",
        r"\brm\s+-rf\b",
        r"\bwrite\b.*\b(file|secret|env|database)\b",
    )
)

_FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(execute|place|submit|cancel)\b.*\b(trade|order)\b",
        r"\btrade\b.*\b(now|immediately|on\s+exchange)\b",
        r"\bdeploy\b",
        r"\bdelete\b",
        r"\bterminate\b",
        r"\bmerge\b",
        r"\bmodify\b.*\bsecret",
        r"\bchange\b.*\bsecret",
        r"\bwrite\b.*\b(file|secret|env|database)\b",
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
        "search_logs",
        "query_database",
        "diagnose_open_orders",
        "search_repository",
        "count_open_orders",
        "count_orders",
        "query_positions",
        "inspect_container",
        "inspect_repository",
        "inspect_runtime",
        "inspect_health",
        "inspect_costs",
        "gather_logs",
        "analyze_failure",
        "identify_root_cause",
        "recommend_fix",
        "inspect_code",
        "summarize_architecture",
        "summarize_modules",
        "run_investigation",
        "reconcile_exchange",
        "reconcile_crypto_com_open_orders",
    }
)


def is_investigation_intent(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _INVESTIGATION_INTENT_PATTERNS)


def has_read_only_investigation_guard(text: str) -> bool:
    """True when objective explicitly constrains to read-only investigation."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _READ_ONLY_INVESTIGATION_GUARDS)


def has_read_only_safety_guard(text: str) -> bool:
    """True when objective explicitly forbids deploy/write/merge-style actions."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _READ_ONLY_SAFETY_GUARDS)


def has_destructive_intent(text: str) -> bool:
    """True when objective contains trading, write, or destructive actions."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    destructive = _matching_patterns(normalized, _DESTRUCTIVE_INVESTIGATION_PATTERNS, skip_negated=True)
    if destructive:
        return True
    return bool(_matching_patterns(normalized, _FORBIDDEN_PATTERNS, skip_negated=True))


def _is_negated_match(text: str, match: re.Match[str]) -> bool:
    """True when a dangerous-token match is preceded by negation in the same clause."""
    prefix = text[: match.start()]
    window = prefix[-96:] if len(prefix) > 96 else prefix
    return bool(_NEGATION_BEFORE_ACTION_RE.search(window))


def _matching_patterns(
    text: str,
    patterns: tuple[re.Pattern[str], ...],
    *,
    skip_negated: bool = False,
) -> list[str]:
    matched: list[str] = []
    for pattern in patterns:
        if not skip_negated:
            if pattern.search(text):
                matched.append(pattern.pattern)
            continue
        for occurrence in pattern.finditer(text):
            if not _is_negated_match(text, occurrence):
                matched.append(pattern.pattern)
                break
    return matched


def classify_text_with_reason(text: str) -> dict[str, Any]:
    """Classify objective safety and return which rule fired (for diagnostics)."""
    normalized = (text or "").strip()
    if not normalized:
        return {"level": SafetyLevel.SAFE_AUTO.value, "rule": "empty_objective", "category": "default"}

    if is_investigation_intent(normalized) and has_read_only_investigation_guard(normalized):
        return {
            "level": SafetyLevel.SAFE_AUTO.value,
            "rule": "read_only_investigation_guard",
            "category": "read_only_investigation",
        }

    # Affirmative dangerous actions must win over negated safety constraints in mixed objectives.
    destructive = _matching_patterns(normalized, _DESTRUCTIVE_INVESTIGATION_PATTERNS, skip_negated=True)
    if destructive:
        category = "destructive_investigation" if is_investigation_intent(normalized) else "forbidden_pattern"
        return {
            "level": SafetyLevel.FORBIDDEN.value,
            "rule": destructive[0],
            "category": category,
        }

    forbidden = _matching_patterns(normalized, _FORBIDDEN_PATTERNS, skip_negated=True)
    if forbidden:
        return {"level": SafetyLevel.FORBIDDEN.value, "rule": forbidden[0], "category": "forbidden_pattern"}

    if has_read_only_safety_guard(normalized):
        return {
            "level": SafetyLevel.SAFE_AUTO.value,
            "rule": "read_only_safety_guard",
            "category": "read_only_investigation",
        }

    if is_investigation_intent(normalized):
        return {
            "level": SafetyLevel.SAFE_AUTO.value,
            "rule": "investigation_intent",
            "category": "read_only_investigation",
        }

    needs_approval = _matching_patterns(normalized, _NEEDS_APPROVAL_PATTERNS, skip_negated=True)
    if needs_approval:
        return {
            "level": SafetyLevel.NEEDS_APPROVAL.value,
            "rule": needs_approval[0],
            "category": "needs_approval_pattern",
        }

    return {"level": SafetyLevel.SAFE_AUTO.value, "rule": "default_safe", "category": "default"}


def classify_text(text: str) -> SafetyLevel:
    result = classify_text_with_reason(text)
    return SafetyLevel(result["level"])


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
        r"\b(execute|place|submit|cancel)\b.*\b(trade|order)\b",
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
