"""
Task Compiler: Telegram intent → structured Notion task.

Creates properly structured Investigation tasks in Notion from free-text intent
(e.g. from /task in Telegram). Validates and normalizes before creation so the
existing automation pipeline (auto-promote → scheduler → execution) can pick them up.

Production-safe: preflight check, graceful failure, local fallback when Notion
is unavailable. No silent failures.

Logging: telegram_task_received, task_compiled, notion_task_created, task_validated,
notion_preflight_failed, fallback_task_created, notion_task_creation_failed.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.services.notion_tasks import (
    ALLOWED_TASK_STATUSES,
    TERMINAL_STATUSES,
    append_telegram_input_to_task,
    clear_last_notion_create_failure,
    create_notion_task,
    get_last_notion_create_failure,
    notion_is_configured,
    notion_status_to_display,
    update_notion_task_priority,
    update_notion_task_status,
)
from app.services.task_fallback_store import (
    get_pending_fallback_tasks,
    remove_fallback_task,
    store_fallback_task,
)
from app.services.notion_task_reader import get_tasks_by_status

logger = logging.getLogger(__name__)

# Active (non-terminal) statuses when searching for similar tasks. Excludes Done, Deployed, Rejected.
ACTIVE_STATUSES_FOR_SIMILARITY = [
    "planned",
    "backlog",
    "ready-for-investigation",
    "investigating",
    "in-progress",
    "investigation-complete",
    "ready-for-patch",
    "patching",
    "testing",
    "release-candidate-ready",
    "ready-for-deploy",
    "awaiting-deploy-approval",
    "deploying",
    "blocked",
    "needs-revision",
]

# Similarity threshold (0.0–1.0). Intent vs existing task: keyword overlap >= this to reuse.
SIMILARITY_THRESHOLD = 0.6

# Max recent tasks to fetch from Notion when looking for similar.
MAX_RECENT_TASKS_FOR_SIMILARITY = 50

# Stopwords for similarity (lowercase). Simple set for deterministic overlap.
_STOPWORDS = frozenset(
    "a an and are as at be but by for if in is it no not of on or so the to was were will".split()
)

# User-facing error keys for Telegram messages (no silent failures)
ERROR_NOTION_NOT_CONFIGURED = "Notion is not configured"
ERROR_NOTION_UNAVAILABLE = "Notion unavailable"

# Defaults for Telegram-sourced tasks (aligned with auto-promote and pipeline)
DEFAULT_STATUS = "planned"
DEFAULT_TYPE = "Investigation"
DEFAULT_EXECUTION_MODE = "Strict"
DEFAULT_SOURCE = "Carlos"
DEFAULT_PROJECT = "Operations"

# Allowed values for validation (internal lowercase where applicable)
ALLOWED_TYPES_NORMALIZED = {
    "investigation", "bug", "monitoring", "improvement", "patch", "strategy",
    "automation", "infrastructure", "content", "deploy",
}
EXECUTION_MODE_VALUES = {"strict", "normal"}

# Task type inference: (keyword_phrases, inferred_type). First match wins; case-insensitive.
# Order matters: more specific phrases first. Default to Investigation when no match.
TASK_TYPE_INFERENCE_RULES: list[tuple[tuple[str, ...], str]] = [
    # Investigation: investigate, why, figure out, look into (before Bug so "figure out why sync fails" -> Investigation)
    (("investigate ", "investigate why", "why does", "why is ", "why are", "figure out", "look into", "root cause", "find out why"), "Investigation"),
    # Patch: apply patch, update code, patch for (before Bug so "apply patch for the SSL fix" -> Patch)
    (("apply patch", "update code", "patch for", "implement fix", "patch to", "code change"), "Patch"),
    # Bug: fix, bug, not working, broken, fails, error
    (("fix ", "fix the", "bug ", "bug in", "not working", "broken", " fails", "failing", "error in", "fix bug"), "Bug"),
    # Monitoring: monitor, watch, check if, alert when, ensure that
    (("monitor ", "monitor the", "watch ", "watch for", "check if ", "alert when", "ensure that "), "Monitoring"),
    # Content: write, create post, draft, document (before Deploy so "write the runbook for deploy" -> Content)
    (("write ", "write a", "create post", "create a post", "draft ", "document ", "doc for", "documentation for"), "Content"),
    # Deploy: deploy, push to prod, release to, roll out
    (("deploy ", "deploy to", "push to prod", "release to prod", "ship to prod", "roll out"), "Deploy"),
]

# Priority scoring: 0–100. Type base + keyword boosts. Cap at 100.
PRIORITY_TYPE_WEIGHT: dict[str, int] = {
    "Bug": 40,
    "Investigation": 30,
    "Patch": 25,
    "Deploy": 35,
    "Monitoring": 20,
    "Content": 10,
}
PRIORITY_URGENCY_KEYWORDS = ("urgent", "now", "asap", "immediately")
PRIORITY_PRODUCTION_KEYWORDS = ("production", "prod", "live", "trading", "orders")
PRIORITY_FAILURE_KEYWORDS = ("not working", "fails", "error", "broken", "blocks", "blocking", "prevents")
PRIORITY_OPERATIONAL_KEYWORDS = ("operational", "incident", "workflow", "intake", "affects")
PRIORITY_REUSED_BOOST = 15
PRIORITY_CAP = 100
PRIORITY_LOW_THRESHOLD = 20  # Scheduler ignores tasks below this unless idle

# Value scoring (0–100) for task prioritization. NEVER blocks creation.
# Used only to assign priority (low/medium/high) and status (queued vs planned).
VALUE_IMPACT_KEYWORDS = ("production", "prod", "orders", "trading", "revenue", "live")
VALUE_URGENCY_KEYWORDS = ("urgent", "now", "asap")
VALUE_FAILURE_KEYWORDS = ("error", "not working", "broken", "fails", "failing", "blocks", "blocking", "prevents")
VALUE_STRATEGIC_KEYWORDS = ("architecture", "core", "system", "security")
# Operational/production-blocking: task intake, incident response, agent workflow
VALUE_OPERATIONAL_KEYWORDS = ("operational", "incident", "workflow", "intake", "affects", "blocks", "blocking", "prevents")
VALUE_NOISE_KEYWORDS = ("test", "experiment", "try", "maybe")
VALUE_CREATION_THRESHOLD = 30  # Below this: low-impact, assign status=queued, priority=low (never blocks)
VALUE_EXECUTION_MIN = 30  # Scheduler may deprioritize; never blocks creation
VALUE_SAFETY_PRIORITY_MIN = 60  # High-priority tasks get status=planned
VALUE_CAP = 100

# Priority labels for user-facing output
PRIORITY_LABEL_LOW = "low"
PRIORITY_LABEL_MEDIUM = "medium"
PRIORITY_LABEL_HIGH = "high"


def _value_text(task: dict[str, Any], intent_text: str = "") -> str:
    """Combined text for value/impact scoring. Includes title, details, objective, intent."""
    return f"{(task.get('title') or '')} {(task.get('details') or '')} {(task.get('objective') or '')} {(task.get('task') or '')} {intent_text}".lower()


def compute_task_value(task: dict[str, Any], intent_text: str = "") -> int:
    """
    Compute a 0–100 value score for gating. Deterministic.

    Boosts: Impact (+40), Urgency (+30), Failure (+30), Strategic (+20), Operational (+25).
    Penalty: Noise (-20). Cap 0–100.
    """
    score = 0
    text = _value_text(task, intent_text)
    if any(kw in text for kw in VALUE_IMPACT_KEYWORDS):
        score += 40
    if any(kw in text for kw in VALUE_URGENCY_KEYWORDS):
        score += 30
    if any(kw in text for kw in VALUE_FAILURE_KEYWORDS):
        score += 30
    if any(kw in text for kw in VALUE_STRATEGIC_KEYWORDS):
        score += 20
    if any(kw in text for kw in VALUE_OPERATIONAL_KEYWORDS):
        score += 25
    if any(kw in text for kw in VALUE_NOISE_KEYWORDS):
        score -= 20
    capped = max(0, min(VALUE_CAP, score))
    logger.info(
        "task_value_computed score=%d impact=%s urgency=%s failure=%s operational=%s text_len=%d",
        capped,
        any(kw in text for kw in VALUE_IMPACT_KEYWORDS),
        any(kw in text for kw in VALUE_URGENCY_KEYWORDS),
        any(kw in text for kw in VALUE_FAILURE_KEYWORDS),
        any(kw in text for kw in VALUE_OPERATIONAL_KEYWORDS),
        len(text),
    )
    return capped


def _value_gate_safety_pass(task: dict[str, Any], priority: int, intent_text: str = "") -> bool:
    """True if we must never treat as low-impact: Bug type, production/operational text, or priority > 60."""
    if priority is not None and priority > VALUE_SAFETY_PRIORITY_MIN:
        return True
    type_val = (task.get("type") or "").strip().lower()
    if type_val == "bug":
        return True
    text = _value_text(task, intent_text)
    if any(kw in text for kw in VALUE_IMPACT_KEYWORDS):
        return True
    if any(kw in text for kw in VALUE_OPERATIONAL_KEYWORDS):
        return True
    return False


def _low_impact_reasons(task: dict[str, Any], intent_text: str = "") -> list[str]:
    """Reasons for low-impact classification (debugging only; never blocks creation)."""
    text = _value_text(task, intent_text)
    reasons = []
    if not any(kw in text for kw in VALUE_IMPACT_KEYWORDS) and not any(kw in text for kw in VALUE_FAILURE_KEYWORDS) and not any(kw in text for kw in VALUE_OPERATIONAL_KEYWORDS):
        reasons.append("low impact")
    if not any(kw in text for kw in VALUE_URGENCY_KEYWORDS):
        reasons.append("no urgency")
    if not any(kw in text for kw in VALUE_FAILURE_KEYWORDS):
        reasons.append("no failure signal")
    return reasons[:3]  # cap for message


def _priority_score_to_label(priority_score: int) -> str:
    """Map 0–100 priority score to low/medium/high. Never blocks creation."""
    if priority_score >= 67:
        return PRIORITY_LABEL_HIGH
    if priority_score >= 34:
        return PRIORITY_LABEL_MEDIUM
    return PRIORITY_LABEL_LOW


def _priority_label_for_notion(label: str) -> str:
    """Capitalize for Notion display (Low, Medium, High)."""
    return (label or "medium").capitalize()


def _is_low_impact(value_score: int, priority_score: int, task: dict[str, Any], intent_text: str = "") -> bool:
    """True if task would have been classified as low-impact (for status/priority assignment only)."""
    if _value_gate_safety_pass(task, priority_score, intent_text):
        return False
    return value_score < VALUE_CREATION_THRESHOLD


def compute_task_priority(task: dict[str, Any], intent_text: str = "", *, reused: bool = False) -> int:
    """
    Compute a 0–100 priority score for a task. Deterministic.

    Base: type weight (Bug 40, Investigation 30, Patch 25, Deploy 35, Monitoring 20, Content 10).
    Boosts: urgency (+30), production impact (+25), failure indicators (+20), operational (+20), reused (+15).
    Cap at 100.
    """
    score = 0
    type_val = (task.get("type") or "").strip()
    score += PRIORITY_TYPE_WEIGHT.get(type_val, PRIORITY_TYPE_WEIGHT.get("Investigation", 30))
    text = f"{(task.get('title') or '')} {(task.get('details') or '')} {(task.get('objective') or '')} {intent_text}".lower()
    if any(kw in text for kw in PRIORITY_URGENCY_KEYWORDS):
        score += 30
    if any(kw in text for kw in PRIORITY_PRODUCTION_KEYWORDS):
        score += 25
    if any(kw in text for kw in PRIORITY_FAILURE_KEYWORDS):
        score += 20
    if any(kw in text for kw in PRIORITY_OPERATIONAL_KEYWORDS):
        score += 20
    if reused:
        score += PRIORITY_REUSED_BOOST
    capped = max(0, min(PRIORITY_CAP, score))
    logger.info("task_priority_computed score=%d type=%s reused=%s", capped, type_val or "?", reused)
    return capped


def _tokenize_for_similarity(text: str) -> set[str]:
    """Lowercase, remove stopwords, return set of words (alphanumeric tokens). Deterministic."""
    if not text or not isinstance(text, str):
        return set()
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return set(t for t in tokens if t and t not in _STOPWORDS and len(t) > 1)


def _similarity_score(intent_tokens: set[str], task_title: str, task_details: str) -> float:
    """
    Overlap of intent tokens with task text (title + details).
    Returns ratio: |intent ∩ task| / max(|intent|, 1). So intent must be largely reflected in task.
    """
    if not intent_tokens:
        return 0.0
    task_text = f"{task_title or ''} {task_details or ''}"
    task_tokens = _tokenize_for_similarity(task_text)
    if not task_tokens:
        return 0.0
    overlap = len(intent_tokens & task_tokens)
    return overlap / len(intent_tokens)


def find_similar_task(intent_text: str) -> Optional[dict[str, Any]]:
    """
    Check if a similar active task already exists in Notion.
    Fetches recent active tasks (excludes terminal: Done, Deployed, Rejected), compares
    keyword overlap with intent. If similarity >= threshold, returns that task dict.

    Returns None if no similar task or Notion not configured. Never raises.
    """
    if not notion_is_configured():
        return None
    intent_text = (intent_text or "").strip()
    if not intent_text:
        return None
    intent_tokens = _tokenize_for_similarity(intent_text)
    if not intent_tokens:
        return None
    try:
        candidates = get_tasks_by_status(
            ACTIVE_STATUSES_FOR_SIMILARITY,
            max_results=MAX_RECENT_TASKS_FOR_SIMILARITY,
        )
    except Exception as e:
        logger.warning("find_similar_task get_tasks_by_status failed: %s", e)
        return None
    best_task: Optional[dict[str, Any]] = None
    best_score = 0.0
    for t in candidates:
        status = (t.get("status") or "").strip().lower()
        if status in TERMINAL_STATUSES:
            continue
        title = (t.get("task") or "").strip()
        details = (t.get("details") or "").strip()
        score = _similarity_score(intent_tokens, title, details)
        if score >= SIMILARITY_THRESHOLD and score > best_score:
            best_score = score
            best_task = t
    if best_task:
        logger.info(
            "duplicate_task_detected task_id=%s title=%r score=%.2f",
            (best_task.get("id") or "")[:12],
            (best_task.get("task") or "")[:50],
            best_score,
        )
    return best_task


def infer_task_type(intent_text: str) -> str:
    """
    Classify task type from intent using keyword/rule-based inference. Deterministic.
    Returns one of: Investigation, Bug, Patch, Monitoring, Content, Deploy.
    Defaults to Investigation when uncertain.
    """
    raw = (intent_text or "").strip().lower()
    if not raw:
        return DEFAULT_TYPE
    # Normalize for phrase matching: space-padded so "fix" matches "fix " or " fix "
    normalized = " " + raw + " "
    for phrases, task_type in TASK_TYPE_INFERENCE_RULES:
        for phrase in phrases:
            if phrase.lower() in normalized:
                return task_type
    return DEFAULT_TYPE


def _infer_title(intent_text: str) -> str:
    """
    Derive a short, clean title from intent. No hallucination; strip and cap length.
    """
    raw = (intent_text or "").strip()
    if not raw:
        return "Untitled task"
    # Take first sentence or first ~60 chars, clean trailing punctuation
    first_line = raw.split("\n")[0].strip()
    if len(first_line) > 80:
        first_line = first_line[:77].rsplit(" ", 1)[0] + "..."
    first_line = re.sub(r"[.\s]+$", "", first_line)
    return first_line or "Untitled task"


def _infer_objective(intent_text: str) -> str:
    """Cleaned explanation of the problem (for Details block). No technical hallucination."""
    raw = (intent_text or "").strip()
    if not raw:
        return "No objective provided."
    return raw[:1500]


def compile_task_from_intent(intent_text: str, user: str = "") -> dict[str, Any]:
    """
    Infer task structure from free-text intent.

    Returns a dict with: title, type, status, execution_mode, source, objective, details.
    Does NOT create in Notion; use create_task_from_telegram_intent for that.
    """
    intent_text = (intent_text or "").strip()
    user = (user or "").strip() or DEFAULT_SOURCE

    inferred_type = infer_task_type(intent_text)
    task = {
        "title": _infer_title(intent_text),
        "type": inferred_type,
        "status": DEFAULT_STATUS,
        "execution_mode": DEFAULT_EXECUTION_MODE,
        "source": user,
        "objective": _infer_objective(intent_text),
        "details": intent_text,
    }
    logger.info(
        "task_compiled title=%r type=%s status=%s execution_mode=%s source=%r",
        task["title"][:50],
        task["type"],
        task["status"],
        task["execution_mode"],
        task["source"][:20],
    )
    return task


def validate_and_fix_task(task: dict[str, Any]) -> tuple[dict[str, Any], Optional[str]]:
    """
    Validate and normalize task fields. Fix silently when possible.

    Returns (fixed_task, None) on success, or (task, error_message) on unrecoverable failure.
    """
    if not task or not isinstance(task, dict):
        return task, "task must be a non-empty dict"

    fixed = dict(task)

    # Status: must be one of allowed → default to Planned (internal: planned)
    status = (fixed.get("status") or "").strip().lower()
    if status not in ALLOWED_TASK_STATUSES:
        fixed["status"] = DEFAULT_STATUS
    else:
        fixed["status"] = status

    # Type: normalize to allowed; default Investigation. Accept inferred types (Investigation, Bug, Patch, Monitoring, Content, Deploy).
    type_val = (fixed.get("type") or "").strip()
    type_lower = type_val.lower()
    if type_lower not in ALLOWED_TYPES_NORMALIZED:
        fixed["type"] = DEFAULT_TYPE

    # Execution Mode: must exist → default Strict
    exec_mode = (fixed.get("execution_mode") or "").strip()
    if not exec_mode:
        fixed["execution_mode"] = DEFAULT_EXECUTION_MODE
    else:
        normalized = exec_mode.lower()
        if normalized not in EXECUTION_MODE_VALUES:
            fixed["execution_mode"] = DEFAULT_EXECUTION_MODE

    # Source: must not be empty → default Carlos
    if not (fixed.get("source") or "").strip():
        fixed["source"] = DEFAULT_SOURCE

    # Title: must not be empty
    if not (fixed.get("title") or "").strip():
        logger.error("task_validated failure: title empty")
        return fixed, "Title must not be empty"

    # Objective must not be empty (we use it in details)
    if not (fixed.get("objective") or "").strip():
        logger.error("task_validated failure: objective empty")
        return fixed, "Objective must not be empty"

    logger.info(
        "task_validated title=%r status=%s type=%s execution_mode=%s",
        (fixed.get("title") or "")[:50],
        fixed.get("status"),
        fixed.get("type"),
        fixed.get("execution_mode"),
    )
    return fixed, None


def create_task_from_telegram_intent(intent_text: str, user: str = "") -> dict[str, Any]:
    """
    Parse intent → compile → validate → create Notion task.

    Returns:
        On success: {"task_id": "...", "title": "...", "status": "Planned", "ok": True}
        On failure: {"ok": False, "error": "..."}

    Does NOT overwrite or edit existing tasks; only creates new ones.
    """
    raw_intent = (intent_text or "").strip()
    logger.info(
        "task_compiler_intent raw_intent_len=%s user=%s raw_preview=%s",
        len(raw_intent), (user or "")[:30], repr(raw_intent[:150]),
    )
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("telegram_task_received", details={"intent_len": len(intent_text or ""), "user": (user or "")[:30]})
    except Exception:
        pass

    compiled = compile_task_from_intent(intent_text, user)
    task, err = validate_and_fix_task(compiled)
    if err:
        logger.warning("task_compiler validation failed: %s", err)
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("task_creation_rejected", details={"reason": err, "intent_preview": (intent_text or "")[:100]})
        except Exception:
            pass
        return {"ok": False, "error": err}

    # Preflight: Never fail silently. If Notion is not configured, return clear error.
    if not notion_is_configured():
        logger.error("notion_preflight_failed NOTION_API_KEY or NOTION_TASK_DB missing")
        return {"ok": False, "error": ERROR_NOTION_NOT_CONFIGURED}

    # Reuse similar existing task instead of creating a duplicate.
    # CRITICAL: Always persist the new Telegram input to the existing task (never discard).
    existing = find_similar_task(intent_text)
    if existing:
        task_id = (existing.get("id") or "").strip()
        title = (existing.get("task") or "").strip()
        status_internal = (existing.get("status") or "").strip().lower()
        status_display = notion_status_to_display(status_internal)
        logger.info("similar_task_detected task_id=%s title=%r status=%s", task_id[:12] if task_id else "?", title[:50], status_display)
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("similar_task_detected", task_id=task_id, task_title=title[:80], details={"intent_preview": (intent_text or "")[:100]})
        except Exception:
            pass

        # Always append the new Telegram input to the existing task (full traceability)
        input_merged = append_telegram_input_to_task(task_id, intent_text, user)
        if input_merged:
            logger.info("telegram_input_merged_into_existing_task task_id=%s", task_id[:12] if task_id else "?")
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("telegram_input_merged_into_existing_task", task_id=task_id, task_title=title[:80], details={"intent_len": len(intent_text or "")})
                log_agent_event("notion_task_updated_from_telegram", task_id=task_id, task_title=title[:80], details={"merged": True})
            except Exception:
                pass
        else:
            logger.warning("telegram_input_dropped_after_match task_id=%s append_failed", task_id[:12] if task_id else "?")
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("telegram_input_dropped_after_match", task_id=task_id, task_title=title[:80], details={"reason": "append_failed", "intent_preview": (intent_text or "")[:100]})
            except Exception:
                pass

        # Recompute priority with reused boost and update in Notion
        reused_priority = compute_task_priority(
            {"title": title, "type": existing.get("type"), "details": existing.get("details")},
            intent_text,
            reused=True,
        )
        if update_notion_task_priority(task_id, reused_priority):
            logger.info("task_priority_updated task_id=%s priority=%d", task_id[:12] if task_id else "?", reused_priority)
        # Optional boost: if Planned, move to Ready for Investigation so pipeline picks it up
        if status_internal == "planned":
            update_notion_task_status(
                task_id,
                "ready-for-investigation",
                append_comment="Re-triggered via Telegram; moved to Ready for Investigation.",
            )
            status_display = notion_status_to_display("ready-for-investigation")

        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("task_created", task_id=task_id, task_title=title[:80], details={"reused": True, "input_merged": input_merged})
            log_agent_event("notion_sync_succeeded", task_id=task_id, task_title=title[:80], details={"source": "telegram", "reused": True, "input_merged": input_merged})
        except Exception:
            pass

        return {
            "ok": True,
            "reused": True,
            "input_merged": input_merged,
            "task_id": task_id,
            "title": title,
            "status": status_display,
            "type": (existing.get("type") or "").strip() or DEFAULT_TYPE,
            "priority": reused_priority,
            "priority_label": _priority_score_to_label(reused_priority),
        }

    # Build details: objective + original intent (for pipeline and audit)
    details = (task.get("objective") or "").strip()
    if (task.get("details") or "").strip() and task.get("details") != task.get("objective"):
        details = details + "\n\nOriginal intent:\n" + (task.get("details") or "").strip()

    # Compute priority and value for prioritization only. NEVER block creation.
    priority_score = compute_task_priority(task, intent_text, reused=False)
    value_score = compute_task_value(task, intent_text)
    priority_label = _priority_score_to_label(priority_score)

    # Low-impact: assign status=backlog (queued), priority=low. User decides what matters.
    is_low_impact = _is_low_impact(value_score, priority_score, task, intent_text)
    title_preview = (task.get("title") or "")[:80]
    logger.info(
        "task_compiler_impact decision title=%s value_score=%d priority_score=%d is_low_impact=%s safety_pass=%s",
        repr(title_preview), value_score, priority_score, is_low_impact, _value_gate_safety_pass(task, priority_score, intent_text),
    )
    if is_low_impact:
        task_status = "backlog"  # queued; Backlog is in Notion schema
        task_priority_label = PRIORITY_LABEL_LOW
        reasons = _low_impact_reasons(task, intent_text)
        logger.info(
            "task_compiler_low_impact reasons=%s value=%d priority=%d",
            reasons, value_score, priority_score,
        )
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "task_created_low_priority",
                task_title=(task.get("title") or "")[:200],
                details={
                    "value": value_score,
                    "priority": priority_score,
                    "reasons": reasons,
                    "status": task_status,
                },
            )
        except Exception:
            pass
        logger.info(
            "task_created_low_priority value=%d priority=%d reasons=%s status=%s",
            value_score, priority_score, reasons, task_status,
        )
    else:
        task_status = (task.get("status") or DEFAULT_STATUS).strip()
        task_priority_label = priority_label

    # Create in Notion via existing integration (always; never reject)
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("notion_sync_started", task_title=(task.get("title") or "")[:80], details={"source": "telegram"})
    except Exception:
        pass

    page = create_notion_task(
        title=(task.get("title") or "Untitled").strip(),
        project=DEFAULT_PROJECT,
        type=(task.get("type") or DEFAULT_TYPE).strip(),
        details=details,
        status=task_status,
        source=(task.get("source") or DEFAULT_SOURCE).strip(),
        execution_mode=(task.get("execution_mode") or DEFAULT_EXECUTION_MODE).strip(),
        priority=_priority_label_for_notion(task_priority_label),
        priority_score=priority_score,
    )

    if page and page.get("dedup_skipped"):
        logger.info(
            "notion_task_dedup_cooldown_skip title=%r (not an API failure; same signature recently created)",
            (task.get("title") or "")[:80],
        )
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "notion_sync_skipped_dedup_cooldown",
                task_title=(task.get("title") or "")[:80],
                details={"source": "telegram"},
            )
        except Exception:
            pass
        status_display = notion_status_to_display(task_status)
        return {
            "ok": True,
            "dedup_cooldown": True,
            "task_id": "",
            "title": (task.get("title") or "").strip(),
            "status": status_display,
            "type": (task.get("type") or DEFAULT_TYPE).strip(),
            "priority": priority_score,
            "priority_label": task_priority_label,
        }

    if not page or page.get("dry_run"):
        if page and page.get("dry_run"):
            logger.info("notion_task_created dry_run=True task_id=dry-run-fake-id")
            return {
                "ok": True,
                "task_id": "dry-run-fake-id",
                "title": (task.get("title") or "").strip(),
                "status": notion_status_to_display(task_status),
                "type": (task.get("type") or DEFAULT_TYPE).strip(),
                "priority": priority_score,
                "priority_label": task_priority_label,
            }
        logger.error(
            "notion_task_creation_failed create_notion_task returned None (API error or blocked) title=%r",
            (task.get("title") or "")[:50],
        )
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "notion_sync_failed",
                task_title=(task.get("title") or "")[:80],
                details={"reason": "create_notion_task returned None", "source": "telegram"},
            )
        except Exception:
            pass
        # Graceful degradation: store locally so task is not lost; retry will sync later
        fallback_id = store_fallback_task(task)
        if fallback_id:
            return {
                "ok": False,
                "error": ERROR_NOTION_UNAVAILABLE,
                "fallback_stored": True,
                "fallback_id": fallback_id,
            }
        return {"ok": False, "error": "Notion task creation failed and local fallback storage failed"}

    task_id = (page.get("id") or "").strip()
    logger.info("notion_task_created task_id=%s title=%r", task_id[:12] if task_id else "?", (task.get("title") or "")[:50])
    logger.info("new_task_created task_id=%s title=%r priority=%d priority_label=%s", task_id[:12] if task_id else "?", (task.get("title") or "")[:50], priority_score, task_priority_label)
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("task_created", task_id=task_id, task_title=(task.get("title") or "")[:80], details={"priority": priority_score, "priority_label": task_priority_label})
        log_agent_event("notion_sync_succeeded", task_id=task_id, task_title=(task.get("title") or "")[:80], details={"source": "telegram"})
    except Exception:
        pass

    status_display = notion_status_to_display(task_status)
    return {
        "ok": True,
        "task_id": task_id,
        "title": (task.get("title") or "").strip(),
        "status": status_display,
        "type": (task.get("type") or DEFAULT_TYPE).strip(),
        "priority": priority_score,
        "priority_label": task_priority_label,
    }


def create_notion_task_from_telegram_direct(description: str, source: str) -> dict[str, Any]:
    """
    Minimal Telegram /task path: single Notion API create only.

    Does not use OpenClaw, LLMs, compile_task_from_intent, find_similar_task,
    or agent_activity_log. Only validates text + notion_is_configured + create_notion_task.
    """
    desc = (description or "").strip()
    if not desc:
        return {"ok": False, "error": "empty_description"}

    if not notion_is_configured():
        logger.error("notion_preflight_failed NOTION_API_KEY or NOTION_TASK_DB missing (direct /task)")
        return {"ok": False, "error": ERROR_NOTION_NOT_CONFIGURED}

    title = (desc.split("\n")[0] or "").strip()[:200] or "Telegram task"
    details_body = desc[:15000]
    src = (source or "").strip() or DEFAULT_SOURCE

    clear_last_notion_create_failure()
    try:
        page = create_notion_task(
            title=title,
            project=DEFAULT_PROJECT,
            type=DEFAULT_TYPE,
            details=details_body,
            status="planned",
            source=src,
            execution_mode=DEFAULT_EXECUTION_MODE,
            priority_score=50,
        )
    except Exception as ex:
        logger.exception("create_notion_task_from_telegram_direct: create_notion_task raised: %s", ex)
        return {"ok": False, "error": str(ex)[:500]}

    if page and page.get("dedup_skipped"):
        return {"ok": True, "dedup_cooldown": True, "title": title}
    if page and page.get("dry_run"):
        return {
            "ok": True,
            "task_id": page.get("id"),
            "title": title,
            "status": "Planned",
            "type": DEFAULT_TYPE,
            "priority": 50,
            "priority_label": "medium",
            "reused": False,
            "dry_run": True,
        }
    if not page:
        detail = (get_last_notion_create_failure() or "").strip()
        if not detail:
            detail = "Notion API did not return a page (see notion_sync_failed in logs)"
        return {"ok": False, "error": detail}

    tid = (page.get("id") or "").strip()
    return {
        "ok": True,
        "task_id": tid,
        "title": title,
        "status": "Planned",
        "type": DEFAULT_TYPE,
        "priority": 50,
        "priority_label": "medium",
        "reused": False,
    }


def retry_failed_notion_tasks() -> int:
    """
    Push pending fallback tasks to Notion. Called from the scheduler each cycle.
    On success, removes the task from the fallback store and logs fallback_task_synced.

    Returns the number of tasks successfully synced. Does not raise.
    """
    if not notion_is_configured():
        return 0
    synced = 0
    for entry in get_pending_fallback_tasks():
        fallback_id = (entry.get("id") or "").strip()
        task = entry.get("task") or {}
        if not fallback_id or not task:
            continue
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "notion_sync_started",
                task_title=(task.get("title") or "")[:80],
                details={"source": "retry", "fallback_id": fallback_id},
            )
        except Exception:
            pass
        details = (task.get("objective") or "").strip()
        if (task.get("details") or "").strip() and task.get("details") != task.get("objective"):
            details = details + "\n\nOriginal intent:\n" + (task.get("details") or "").strip()
        priority_score = compute_task_priority(task, (task.get("details") or "").strip(), reused=False)
        try:
            page = create_notion_task(
                title=(task.get("title") or "Untitled").strip(),
                project=DEFAULT_PROJECT,
                type=(task.get("type") or DEFAULT_TYPE).strip(),
                details=details,
                status=(task.get("status") or DEFAULT_STATUS).strip(),
                source=(task.get("source") or DEFAULT_SOURCE).strip(),
                execution_mode=(task.get("execution_mode") or DEFAULT_EXECUTION_MODE).strip(),
                priority_score=priority_score,
            )
        except Exception as e:
            logger.warning("retry_failed_notion_tasks create_notion_task failed fallback_id=%s err=%s", fallback_id, e)
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event(
                    "notion_sync_failed",
                    task_title=(task.get("title") or "")[:80],
                    details={"source": "retry", "fallback_id": fallback_id, "error": str(e)},
                )
            except Exception:
                pass
            continue
        if not page or page.get("dry_run"):
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event(
                    "notion_sync_failed",
                    task_title=(task.get("title") or "")[:80],
                    details={"source": "retry", "fallback_id": fallback_id, "reason": "create_notion_task returned None or dry_run"},
                )
            except Exception:
                pass
            continue
        if remove_fallback_task(fallback_id):
            synced += 1
            notion_id = (page.get("id") or "").strip()
            logger.info("fallback_task_synced task_id=%s fallback_id=%s", notion_id[:12] if notion_id else "?", fallback_id)
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event(
                    "notion_sync_succeeded",
                    task_id=notion_id,
                    task_title=(task.get("title") or "")[:80],
                    details={"source": "retry", "fallback_id": fallback_id},
                )
            except Exception:
                pass
    return synced
