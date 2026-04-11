"""LLM-based planner: user input → tool name + args."""

from __future__ import annotations

import logging
from typing import Any

from app.jarvis.bedrock_client import ask_bedrock, extract_planner_json_object
from app.jarvis.plan_validation import PlanValidated, validate_plan_dict
from app.jarvis.tools import TOOL_SPECS, list_tool_names

logger = logging.getLogger(__name__)

# Pre-Bedrock exact phrases (normalized) -> (action, intent_label for logs)
_DIRECT_INTENTS: dict[str, tuple[str, str]] = {
    "list tools": ("list_available_tools", "list_tools"),
    "show tools": ("list_available_tools", "show_tools"),
    "what tools do you have": ("list_available_tools", "what_tools"),
    "pending": ("list_pending_approvals", "pending"),
    "show pending": ("list_pending_approvals", "show_pending"),
    "list pending approvals": ("list_pending_approvals", "list_pending_approvals"),
    "ready": ("list_ready_for_execution", "ready"),
    "ready for execution": ("list_ready_for_execution", "ready_for_execution"),
    "list ready actions": ("list_ready_for_execution", "list_ready_actions"),
}


def _normalize_direct_intent_input(user_input: str) -> str:
    """Lowercase, trim, collapse spaces; strip leading ``/jarvis`` (case-insensitive)."""
    t = (user_input or "").strip()
    if t.lower().startswith("/jarvis"):
        t = t[7:].strip()
    t = " ".join(t.split())
    return t.lower()


def _try_local_direct_plan(user_input: str, jarvis_run_id: str) -> dict[str, Any] | None:
    """
    Deterministic routing for obvious utility phrases; skips Bedrock when matched.
    Matching is exact on normalized text only (no fuzzy / LLM).
    """
    normalized = _normalize_direct_intent_input(user_input)
    if not normalized:
        return None
    hit = _DIRECT_INTENTS.get(normalized)
    if hit is None:
        return None
    action, intent_label = hit
    p = PlanValidated(
        action=action,
        args={},
        reasoning=f"local_intent:{intent_label}",
    )
    out = p.model_dump()
    rid = (jarvis_run_id or "").strip() or "-"
    logger.info(
        "jarvis.planner.local_intent run_id=%s normalized=%r matched=%s action=%s",
        rid,
        normalized,
        intent_label,
        action,
    )
    return out


def _looks_like_time_query(user_input: str) -> bool:
    t = (user_input or "").lower()
    if "time" not in t and "clock" not in t and "hour" not in t:
        return False
    return any(w in t for w in ("what", "when", "current", "server", "utc", "time"))


def _fallback_plan(user_input: str, reason: str) -> dict[str, Any]:
    """Always returns a dict that passes :func:`validate_plan_dict`."""
    if _looks_like_time_query(user_input):
        p = PlanValidated(
            action="get_server_time",
            args={},
            reasoning=f"{reason} (heuristic: time-related query)",
        )
        out = p.model_dump()
        logger.info("jarvis.planner.fallback reason=%s action=%s", reason, out.get("action"))
        return out
    p = PlanValidated(
        action="echo_message",
        args={"message": f"[planner fallback] {reason}: {user_input[:500]}"},
        reasoning=reason,
    )
    out = p.model_dump()
    logger.info("jarvis.planner.fallback reason=%s action=%s", reason, out.get("action"))
    return out


def _tool_lines_for_prompt() -> str:
    lines: list[str] = []
    for name in sorted(TOOL_SPECS.keys()):
        spec = TOOL_SPECS[name]
        arg_hint = "no arguments (use empty object {} for args)"
        if spec.args_model.__name__ != "EmptyArgs":
            arg_hint = "see tool description for required args keys"
        lines.append(f"- {name}: {spec.description} ({arg_hint})")
    return "\n".join(lines)


def create_plan(
    user_input: str,
    *,
    recent_context: str = "",
    jarvis_run_id: str = "",
) -> dict[str, Any]:
    """
    Use Bedrock to choose an action and tool arguments.

    Returns a validated plan dict (action, args, reasoning). On any failure,
    returns a safe fallback plan (same shape).
    """
    text = (user_input or "").strip()
    rid = (jarvis_run_id or "").strip()
    if rid:
        logger.info("jarvis.planner.input run_id=%s chars=%d", rid, len(text))
    else:
        logger.info("jarvis.planner.input chars=%d", len(text))

    direct = _try_local_direct_plan(text, rid)
    if direct is not None:
        return direct

    tools_block = _tool_lines_for_prompt()
    context_block = ""
    if (recent_context or "").strip():
        context_block = f"\nRecent conversation context:\n{recent_context.strip()}\n"

    prompt = f"""You are a planner for an assistant. Choose exactly one tool and JSON arguments.

Available tools:
{tools_block}

Respond with ONLY a single JSON object (no markdown, no commentary) with this exact shape:
{{"action":"<tool_name>","args":{{...}},"reasoning":"<short reason>"}}

Use empty object {{}} for args when the tool has no parameters.

{context_block}
User request: {text}
"""

    try:
        raw = ask_bedrock(prompt)
    except Exception as e:
        logger.exception("jarvis.planner.bedrock_exception run_id=%s err=%s", rid or "-", e)
        return _fallback_plan(user_input, "bedrock_exception")

    logger.info(
        "jarvis.planner.bedrock_raw run_id=%s chars=%d",
        rid or "-",
        len(raw or ""),
    )
    if raw:
        logger.info(
            "jarvis.planner.bedrock_raw_preview run_id=%s preview=%r",
            rid or "-",
            (raw or "")[:600],
        )

    if not raw:
        logger.warning("jarvis.planner.empty_bedrock_response run_id=%s", rid or "-")
        return _fallback_plan(user_input, "empty_bedrock_response")

    parsed = extract_planner_json_object(raw)
    if not parsed:
        logger.warning(
            "jarvis.planner.parse_failed run_id=%s preview=%r",
            rid or "-",
            (raw or "")[:400],
        )
        return _fallback_plan(user_input, "invalid_json")

    validated, err = validate_plan_dict(parsed)
    if validated is None:
        logger.warning(
            "jarvis.planner.validation_failed run_id=%s err=%s raw_keys=%s",
            rid or "-",
            err,
            list(parsed.keys()),
        )
        return _fallback_plan(user_input, "validation_failed")

    out = validated.model_dump()
    logger.info(
        "jarvis.planner.validated run_id=%s action=%s args_keys=%s reasoning_len=%d",
        rid or "-",
        out.get("action"),
        list((out.get("args") or {}).keys()),
        len((out.get("reasoning") or "")),
    )
    return out
