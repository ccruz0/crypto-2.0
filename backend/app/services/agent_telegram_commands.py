"""
Telegram command interface for the multi-agent operator system.

Commands: /investigate, /agent, /help (agent section).
Single bot; backend routes tasks to the correct agent.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Display names (operator-facing) -> agent_id (internal)
AGENT_NAME_TO_ID: dict[str, str] = {
    "sentinel": "telegram_alerts",      # Telegram and Alerts Agent
    "ledger": "execution_state",         # Execution and State Agent
    "archivist": "docs_rules",           # Docs and Rules Agent (planned)
    "architect": "architecture",          # Architecture and Refactor Agent (planned)
    "analyst": "trading_signal",         # Trading Signal Agent (planned)
}

AGENT_ID_TO_DISPLAY: dict[str, str] = {
    "telegram_alerts": "Sentinel",
    "execution_state": "Ledger",
    "docs_rules": "Archivist",
    "architecture": "Architect",
    "trading_signal": "Analyst",
}

# Agents with active handlers (can run apply)
ACTIVE_AGENT_IDS = frozenset({"telegram_alerts", "execution_state"})


def _generate_task_id(chat_id: str) -> str:
    """Generate a unique task ID for Telegram-initiated tasks."""
    return f"tg-{int(time.time())}-{abs(hash(chat_id)) % 10000:04d}"


def parse_investigate(text: str) -> tuple[bool, str]:
    """
    Parse /investigate command. Everything after the command is the problem text.
    Returns (ok, problem_text or error_message).
    """
    # text is the full message; we expect "/investigate <problem>"
    rest = text[len("/investigate"):].strip() if text.lower().startswith("/investigate") else text.strip()
    if not rest:
        return False, "Usage: /investigate <problem text>\nExample: /investigate repeated BTC alerts"
    return True, rest


def parse_agent(text: str) -> tuple[bool, Optional[str], str]:
    """
    Parse /agent command. First token = agent name, rest = problem text.
    Returns (ok, agent_id or None, problem_text or error_message).
    agent_id is None when agent name is invalid.
    """
    # text is the full message; we expect "/agent <agent_name> <problem>"
    rest = text[len("/agent"):].strip() if text.lower().startswith("/agent") else text.strip()
    if not rest:
        return False, None, "Usage: /agent <agent_name> <problem text>"
    parts = rest.split(None, 1)  # max 2 parts: agent_name, problem
    agent_name = parts[0].strip().lower()
    problem = parts[1].strip() if len(parts) > 1 else ""
    if not problem:
        return False, None, (
            f"Usage: /agent <agent_name> <problem text>\n"
            f"Valid agents: {', '.join(AGENT_NAME_TO_ID.keys())}"
        )
    agent_id = AGENT_NAME_TO_ID.get(agent_name)
    if agent_id is None:
        return False, None, (
            f"Unknown agent: {agent_name}\n"
            f"Valid agents: {', '.join(AGENT_NAME_TO_ID.keys())}"
        )
    return True, agent_id, problem


def _build_prepared_task(problem_text: str, task_id: str, forced_agent_id: Optional[str] = None) -> dict[str, Any]:
    """Build a prepared_task dict for the routing/callback layer."""
    task: dict[str, Any] = {
        "id": task_id,
        "task": problem_text,
        "details": problem_text,
    }
    if forced_agent_id:
        task["type"] = forced_agent_id  # hint for routing fallback
    prepared: dict[str, Any] = {
        "task": task,
        "repo_area": {},
    }
    if forced_agent_id:
        prepared["_forced_agent_id"] = forced_agent_id
    return prepared


def _get_callbacks_for_forced_agent(forced_agent_id: str) -> Optional[dict[str, Any]]:
    """Get callback pack for a forced agent. Returns None if agent not active."""
    if forced_agent_id not in ACTIVE_AGENT_IDS:
        return None
    try:
        from app.services.agent_routing import (
            AGENT_EXECUTION_STATE,
            AGENT_TELEGRAM_ALERTS,
            get_file_prefix,
            get_save_subdir,
        )
        from app.services.agent_callbacks import (
            _make_openclaw_callback,
            _make_openclaw_validator,
            _make_openclaw_verifier,
        )
        from app.services.openclaw_client import (
            AGENT_OUTPUT_SECTIONS,
            build_execution_state_prompt,
            build_telegram_alerts_prompt,
        )
        save_subdir = get_save_subdir(forced_agent_id)
        file_prefix = get_file_prefix(forced_agent_id)
        if forced_agent_id == AGENT_TELEGRAM_ALERTS:
            return {
                "apply_change_fn": _make_openclaw_callback(
                    build_telegram_alerts_prompt,
                    save_subdir, file_prefix,
                    use_agent_schema=True,
                ),
                "validate_fn": _make_openclaw_validator(
                    save_subdir, file_prefix, sections=AGENT_OUTPUT_SECTIONS
                ),
                "verify_solution_fn": _make_openclaw_verifier(save_subdir, file_prefix),
                "selection_reason": "Telegram and Alerts agent (forced by operator)",
            }
        if forced_agent_id == AGENT_EXECUTION_STATE:
            return {
                "apply_change_fn": _make_openclaw_callback(
                    build_execution_state_prompt,
                    save_subdir, file_prefix,
                    use_agent_schema=True,
                ),
                "validate_fn": _make_openclaw_validator(
                    save_subdir, file_prefix, sections=AGENT_OUTPUT_SECTIONS
                ),
                "verify_solution_fn": _make_openclaw_verifier(save_subdir, file_prefix),
                "selection_reason": "Execution and State agent (forced by operator)",
            }
    except Exception as e:
        logger.warning("agent_telegram_commands: get_callbacks_for_forced_agent failed: %s", e)
    return None


def _run_apply_and_validate(prepared_task: dict[str, Any], callbacks: dict[str, Any]) -> dict[str, Any]:
    """Run apply and validate; return combined result."""
    apply_fn = callbacks.get("apply_change_fn")
    validate_fn = callbacks.get("validate_fn")
    if not apply_fn:
        return {"success": False, "summary": "No apply function", "validation": None}
    apply_result = apply_fn(prepared_task)
    if not apply_result.get("success"):
        return {
            "success": False,
            "summary": apply_result.get("summary", "Apply failed"),
            "validation": None,
        }
    validation = None
    if validate_fn:
        validation = validate_fn(prepared_task)
    return {
        "success": True,
        "summary": apply_result.get("summary", "OK"),
        "validation": validation,
        "apply_result": apply_result,
    }


def _get_investigate_debug_preamble() -> str:
    """Return diagnostic preamble when TELEGRAM_INVESTIGATE_DEBUG is enabled."""
    if (os.environ.get("TELEGRAM_INVESTIGATE_DEBUG") or "").strip().lower() in ("1", "true", "yes"):
        try:
            from app.core.runtime_identity import get_runtime_identity, format_runtime_identity_short
            identity = get_runtime_identity()
            return f"🔍 [DEBUG] {format_runtime_identity_short(identity)}\n\n"
        except Exception:
            return ""
    return ""


def handle_investigate_command(chat_id: str, text: str, send_response: Any) -> bool:
    """
    Handle /investigate <problem text>. Route via backend; ack and run.
    send_response: callable(chat_id, message) -> bool
    """
    ok, problem_or_err = parse_investigate(text)
    if not ok:
        logger.info("telegram_command_received command=investigate parsing_failed chat_id=%s", chat_id)
        return send_response(chat_id, problem_or_err)

    # Log runtime identity early (before imports that may fail with pydantic_settings)
    try:
        from app.core.runtime_identity import get_runtime_identity, format_runtime_identity_short
        identity = get_runtime_identity()
        logger.info("runtime_identity command=investigate chat_id=%s identity=%s", chat_id, format_runtime_identity_short(identity))
    except Exception as id_err:
        logger.warning("runtime_identity command=investigate chat_id=%s failed=%s", chat_id, id_err)

    problem_text = problem_or_err
    task_id = _generate_task_id(chat_id)
    prepared_task = _build_prepared_task(problem_text, task_id, forced_agent_id=None)

    try:
        from app.services.agent_routing import route_task_with_reason
        from app.services.agent_callbacks import select_default_callbacks_for_task

        agent_id, route_reason = route_task_with_reason(prepared_task)
        logger.info(
            "command_handler_selected command=investigate chat_id=%s selected_agent=%s route_reason=%s routing=automatic fallback_used=false",
            chat_id, agent_id, route_reason,
        )

        if agent_id is None or route_reason == "no_match":
            # Unclear routing - suggest agents (fallback path)
            logger.info(
                "fallback_used command=investigate chat_id=%s reason=no_match selected_agent=none",
                chat_id,
            )
            debug_preamble = _get_investigate_debug_preamble()
            msg = (
                f"{debug_preamble}No clear specialist matched.\n\n"
                "Suggested agents:\n"
                "• Sentinel — alerting issues\n"
                "• Ledger — order/execution issues\n\n"
                "Try:\n"
                "/agent sentinel investigate repeated alerts\n"
                "/agent ledger investigate missing order state"
            )
            return send_response(chat_id, msg)

        # Check if we have an active handler
        callbacks = select_default_callbacks_for_task(prepared_task)
        apply_fn = callbacks.get("apply_change_fn")
        if not apply_fn:
            # Scaffolded agent - no handler yet (fallback path)
            logger.info(
                "fallback_used command=investigate chat_id=%s reason=scaffolded_agent selected_agent=%s",
                chat_id, agent_id,
            )
            display = AGENT_ID_TO_DISPLAY.get(agent_id, agent_id)
            debug_preamble = _get_investigate_debug_preamble()
            msg = (
                f"{debug_preamble}Agent selected: {display}\n"
                f"Reason: {route_reason}\n"
                f"Status: {display} is planned but not yet active.\n"
                "Use Sentinel or Ledger for now."
            )
            return send_response(chat_id, msg)

        display = AGENT_ID_TO_DISPLAY.get(agent_id, agent_id)
        debug_preamble = _get_investigate_debug_preamble()
        ack = (
            f"{debug_preamble}Task received\n"
            f"Agent selected: {display}\n"
            f"Reason: {route_reason}\n"
            "Mode: analysis"
        )
        send_response(chat_id, ack)

        # Run apply (blocking)
        result = _run_apply_and_validate(prepared_task, callbacks)
        if result.get("success"):
            val = result.get("validation") or {}
            val_ok = val.get("success", False)
            summary = result.get("summary", "")[:100]
            completion = (
                "Run complete\n"
                f"Agent: {display}\n"
                f"Validation: {'PASSED' if val_ok else 'FAILED'}\n"
                f"Summary: {summary}\n"
                "Next: review artifact in docs/agents/"
            )
        else:
            completion = f"Run failed: {result.get('summary', 'unknown')}"
        return send_response(chat_id, completion)

    except Exception as e:
        logger.exception("telegram_command_received command=investigate error=%s chat_id=%s", e, chat_id)
        # Include runtime identity in error when debug enabled (helps trace OpenClaw vs backend-aws)
        try:
            debug_preamble = _get_investigate_debug_preamble()
            return send_response(chat_id, f"{debug_preamble}Error: {e}")
        except Exception:
            return send_response(chat_id, f"Error: {e}")


def handle_agent_command(chat_id: str, text: str, send_response: Any) -> bool:
    """
    Handle /agent <agent_name> <problem text>. Force agent; ack and run.
    send_response: callable(chat_id, message) -> bool
    """
    ok, agent_id, problem_or_err = parse_agent(text)
    if not ok:
        logger.info("telegram_command_received command=agent parsing_failed chat_id=%s", chat_id)
        return send_response(chat_id, problem_or_err)

    problem_text = problem_or_err
    task_id = _generate_task_id(chat_id)
    prepared_task = _build_prepared_task(problem_text, task_id, forced_agent_id=agent_id)

    display = AGENT_ID_TO_DISPLAY.get(agent_id, agent_id)
    logger.info(
        "telegram_command_received command=agent chat_id=%s forced_agent=%s selected_agent=%s routing=forced",
        chat_id, display, agent_id,
    )

    callbacks = _get_callbacks_for_forced_agent(agent_id)
    if not callbacks:
        msg = (
            f"Agent selected: {display}\n"
            "Reason: forced by operator\n"
            f"Status: {display} is planned but not yet active.\n"
            "Active agents: Sentinel, Ledger"
        )
        return send_response(chat_id, msg)

    ack = (
        "Task received\n"
        f"Agent selected: {display}\n"
        "Reason: forced by operator\n"
        "Mode: analysis"
    )
    send_response(chat_id, ack)

    try:
        result = _run_apply_and_validate(prepared_task, callbacks)
        if result.get("success"):
            val = result.get("validation") or {}
            val_ok = val.get("success", False)
            summary = result.get("summary", "")[:100]
            completion = (
                "Run complete\n"
                f"Agent: {display}\n"
                f"Validation: {'PASSED' if val_ok else 'FAILED'}\n"
                f"Summary: {summary}\n"
                "Next: review artifact in docs/agents/"
            )
        else:
            completion = f"Run failed: {result.get('summary', 'unknown')}"
        return send_response(chat_id, completion)
    except Exception as e:
        logger.exception("telegram_command_received command=agent error=%s chat_id=%s", e, chat_id)
        return send_response(chat_id, f"Error: {e}")


def get_agent_help_content() -> str:
    """Return the multi-agent help section for /help."""
    return """

<b>ATP Command Console</b>
This chat/group is the ATP command console. Commands work here.

<b>Channel roles</b>
• HILOVIVO3.0 — alerts-only (signals, orders, reports). No commands.
• Claw — OpenClaw-native only (/new, /reset, /status, /context).
• AWS_alerts — technical alerts only.

<b>Multi-Agent Operations</b>
/task &lt;description&gt; — Create Notion task from Telegram (e.g. /task Investigate alerts).
/investigate &lt;problem&gt; — Describe an issue; backend selects the best agent.
/agent &lt;agent&gt; &lt;problem&gt; — Force a specific agent.
/runtime-check — Verify runtime dependencies.

<b>Agents</b>
• Sentinel — alerts, Telegram, duplicates, missing notifications, throttling
• Ledger — orders, execution state, exchange/DB/dashboard mismatch, lifecycle
• Archivist — docs, rules, runbooks (planned)
• Architect — system design, refactor (planned)
• Analyst — signal behavior, strategy (planned)

<b>Examples</b>
/investigate repeated BTC alerts
/investigate order not in open orders
/agent sentinel investigate repeated alerts
/agent ledger investigate dashboard mismatch for open orders
/runtime-check"""
