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
    create_notion_task,
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
PRIORITY_FAILURE_KEYWORDS = ("not working", "fails", "error", "broken")
PRIORITY_REUSED_BOOST = 15
PRIORITY_CAP = 100
PRIORITY_LOW_THRESHOLD = 20  # Scheduler ignores tasks below this unless idle

# Value scoring (0–100) for task gating: creation and execution.
# Used to reject or skip low-value / noise tasks.
VALUE_IMPACT_KEYWORDS = ("production", "prod", "orders", "trading", "revenue", "live")
VALUE_URGENCY_KEYWORDS = ("urgent", "now", "asap")
VALUE_FAILURE_KEYWORDS = ("error", "not working", "broken", "fails", "failing")
VALUE_STRATEGIC_KEYWORDS = ("architecture", "core", "system", "security")
VALUE_NOISE_KEYWORDS = ("test", "experiment", "try", "maybe")
VALUE_CREATION_THRESHOLD = 30  # Do not create if value < this (unless safety pass)
VALUE_EXECUTION_MIN = 30  # Skip execution if priority < 30 AND value < this (unless safety pass)
VALUE_SAFETY_PRIORITY_MIN = 60  # Never block tasks with priority >= this
VALUE_CAP = 100


def compute_task_value(task: dict[str, Any], intent_text: str = "") -> int:
    """
    Compute a 0–100 value score for gating. Deterministic.

    Boosts: Impact (+40), Urgency (+30), Failure (+30), Strategic (+20).
    Penalty: Noise (-20). Cap 0–100.
    """
    score = 0
    text = f"{(task.get('title') or '')} {(task.get('details') or '')} {(task.get('task') or '')} {intent_text}".lower()
    if any(kw in text for kw in VALUE_IMPACT_KEYWORDS):
        score += 40
    if any(kw in text for kw in VALUE_URGENCY_KEYWORDS):
        score += 30
    if any(kw in text for kw in VALUE_FAILURE_KEYWORDS):
        score += 30
    if any(kw in text for kw in VALUE_STRATEGIC_KEYWORDS):
        score += 20
    if any(kw in text for kw in VALUE_NOISE_KEYWORDS):
        score -= 20
    capped = max(0, min(VALUE_CAP, score))
    logger.debug("task_value_computed score=%d", capped)
    return capped


def _value_gate_safety_pass(task: dict[str, Any], priority: int) -> bool:
    """True if we must never block: Bug type, production-related text, or priority > 60."""
    if priority is not None and priority > VALUE_SAFETY_PRIORITY_MIN:
        return True
    type_val = (task.get("type") or "").strip().lower()
    if type_val == "bug":
        return True
    text = f"{(task.get('title') or '')} {(task.get('details') or '')} {(task.get('task') or '')}".lower()
    if any(kw in text for kw in VALUE_IMPACT_KEYWORDS):
        return True
    return False


def _rejection_reasons(task: dict[str, Any], intent_text: str = "") -> list[str]:
    """Short reasons why the task was rejected (low value)."""
    text = f"{(task.get('title') or '')} {(task.get('details') or '')} {(task.get('task') or '')} {intent_text}".lower()
    reasons = []
    if not any(kw in text for kw in VALUE_IMPACT_KEYWORDS) and not any(kw in text for kw in VALUE_FAILURE_KEYWORDS):
        reasons.append("low impact")
    if not any(kw in text for kw in VALUE_URGENCY_KEYWORDS):
        reasons.append("no urgency")
    if not any(kw in text for kw in VALUE_FAILURE_KEYWORDS):
        reasons.append("no failure signal")
    return reasons[:3]  # cap for message


def compute_task_priority(task: dict[str, Any], intent_text: str = "", *, reused: bool = False) -> int:
    """
    Compute a 0–100 priority score for a task. Deterministic.

    Base: type weight (Bug 40, Investigation 30, Patch 25, Deploy 35, Monitoring 20, Content 10).
    Boosts: urgency (+30), production impact (+25), failure indicators (+20), reused (+15).
    Cap at 100.
    """
    score = 0
    type_val = (task.get("type") or "").strip()
    score += PRIORITY_TYPE_WEIGHT.get(type_val, PRIORITY_TYPE_WEIGHT.get("Investigation", 30))
    text = f"{(task.get('title') or '')} {(task.get('details') or '')} {intent_text}".lower()
    if any(kw in text for kw in PRIORITY_URGENCY_KEYWORDS):
        score += 30
    if any(kw in text for kw in PRIORITY_PRODUCTION_KEYWORDS):
        score += 25
    if any(kw in text for kw in PRIORITY_FAILURE_KEYWORDS):
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
    logger.info("telegram_task_received intent_len=%s user=%s", len(intent_text or ""), (user or "")[:30])

    compiled = compile_task_from_intent(intent_text, user)
    task, err = validate_and_fix_task(compiled)
    if err:
        logger.warning("task_compiler validation failed: %s", err)
        return {"ok": False, "error": err}

    # Preflight: Never fail silently. If Notion is not configured, return clear error.
    if not notion_is_configured():
        logger.error("notion_preflight_failed NOTION_API_KEY or NOTION_TASK_DB missing")
        return {"ok": False, "error": ERROR_NOTION_NOT_CONFIGURED}

    # Reuse similar existing task instead of creating a duplicate
    existing = find_similar_task(intent_text)
    if existing:
        task_id = (existing.get("id") or "").strip()
        title = (existing.get("task") or "").strip()
        status_internal = (existing.get("status") or "").strip().lower()
        status_display = notion_status_to_display(status_internal)
        logger.info("task_reused task_id=%s title=%r status=%s", task_id[:12] if task_id else "?", title[:50], status_display)
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
        return {
            "ok": True,
            "reused": True,
            "task_id": task_id,
            "title": title,
            "status": status_display,
            "type": (existing.get("type") or "").strip() or DEFAULT_TYPE,
            "priority": reused_priority,
        }

    # Build details: objective + original intent (for pipeline and audit)
    details = (task.get("objective") or "").strip()
    if (task.get("details") or "").strip() and task.get("details") != task.get("objective"):
        details = details + "\n\nOriginal intent:\n" + (task.get("details") or "").strip()

    # Compute priority and value for creation and gating
    priority_score = compute_task_priority(task, intent_text, reused=False)
    value_score = compute_task_value(task, intent_text)

    # Creation gate: do not create low-value tasks unless safety pass (Bug, production, priority > 60)
    if not _value_gate_safety_pass(task, priority_score) and value_score < VALUE_CREATION_THRESHOLD:
        reasons = _rejection_reasons(task, intent_text)
        reason_text = "; ".join(reasons) if reasons else "low impact"
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "task_rejected_low_value",
                task_title=(task.get("title") or "")[:200],
                details={"value": value_score, "priority": priority_score, "reasons": reasons},
            )
        except Exception:
            pass
        logger.info("task_rejected_low_value value=%d priority=%d reasons=%s", value_score, priority_score, reasons)
        return {
            "ok": False,
            "error": "This task has low impact and was not created. If this is important, please clarify urgency or impact.",
            "rejected_low_value": True,
            "reasons": reasons,
        }

    # Create in Notion via existing integration
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

    if not page or page.get("dry_run"):
        if page and page.get("dry_run"):
            logger.info("notion_task_created dry_run=True task_id=dry-run-fake-id")
            return {
                "ok": True,
                "task_id": "dry-run-fake-id",
                "title": (task.get("title") or "").strip(),
                "status": notion_status_to_display((task.get("status") or DEFAULT_STATUS).strip()),
                "type": (task.get("type") or DEFAULT_TYPE).strip(),
                "priority": priority_score,
            }
        logger.error("notion_task_creation_failed create_notion_task returned None (dedup or API error) title=%r", (task.get("title") or "")[:50])
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
    logger.info("new_task_created task_id=%s title=%r priority=%d", task_id[:12] if task_id else "?", (task.get("title") or "")[:50], priority_score)

    status_display = notion_status_to_display((task.get("status") or DEFAULT_STATUS).strip())
    return {
        "ok": True,
        "task_id": task_id,
        "title": (task.get("title") or "").strip(),
        "status": status_display,
        "type": (task.get("type") or DEFAULT_TYPE).strip(),
        "priority": priority_score,
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
            continue
        if page and not page.get("dry_run"):
            if remove_fallback_task(fallback_id):
                synced += 1
                notion_id = (page.get("id") or "").strip()
                logger.info("fallback_task_synced task_id=%s fallback_id=%s", notion_id[:12] if notion_id else "?", fallback_id)
    return synced
