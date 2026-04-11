"""Execute validated planner output against the tool registry and policy."""

from __future__ import annotations

import logging
from typing import Any

from app.jarvis.approval_storage import (
    APPROVAL_PENDING,
    EXEC_NOT_EXECUTED,
    build_pending_approval_record,
    get_default_approval_storage,
    utc_now_iso,
)
from app.jarvis.plan_validation import validate_plan_dict
from app.jarvis.runtime_env import get_jarvis_env
from app.jarvis.tools import EXECUTABLE_POLICIES, ToolPolicy, ToolSpec, get_tool_spec

logger = logging.getLogger(__name__)


def tool_allowed_for_current_env(spec: ToolSpec) -> bool:
    return get_jarvis_env() in spec.allowed_envs


def environment_not_allowed_result(tool: str, spec: ToolSpec) -> dict[str, Any]:
    return {
        "status": "environment_not_allowed",
        "tool": tool,
        "current_env": get_jarvis_env(),
        "allowed_envs": sorted(spec.allowed_envs),
        "message": "This tool is not allowed in the current Jarvis environment.",
    }

_APPROVAL_MESSAGE = "Execution requires approval; tool was not run."
_RESTRICTED_MESSAGE = "This tool is restricted and cannot be executed via Jarvis."


def execute_plan(
    plan: dict[str, Any],
    *,
    jarvis_run_id: str | None = None,
) -> Any:
    """
    Validate plan shape, enforce policy, validate tool args, then invoke or defer.

    ``approval_required`` tools return a structured payload without calling ``fn``.
    ``restricted`` tools return a structured denial without calling ``fn``.
    Returns tool result or a structured error/status dict. Does not raise.
    """
    rid = (jarvis_run_id or "").strip() or None

    if not isinstance(plan, dict):
        logger.warning(
            "jarvis.executor.invalid_plan_type run_id=%s type=%s",
            rid,
            type(plan).__name__,
        )
        return {"error": "invalid_plan", "detail": "plan must be a dict"}

    validated, verr = validate_plan_dict(plan)
    if validated is None:
        logger.warning("jarvis.executor.plan_validation_failed run_id=%s err=%s", rid, verr)
        return {"error": "invalid_plan", "detail": verr or "validation_failed"}

    action = validated.action
    args = validated.args

    spec = get_tool_spec(action)
    if spec is None:
        logger.warning("jarvis.executor.unknown_tool run_id=%s action=%r", rid, action)
        return {"error": "unknown_tool", "action": action}

    try:
        validated_args = spec.args_model.model_validate(args)
    except Exception as e:
        logger.warning(
            "jarvis.executor.args_invalid run_id=%s action=%s err=%s",
            rid,
            action,
            e,
        )
        return {
            "error": "args_invalid",
            "action": action,
            "detail": str(e),
        }

    payload = validated_args.model_dump()

    if spec.policy == ToolPolicy.RESTRICTED:
        logger.info(
            "jarvis.executor.restricted run_id=%s tool=%s",
            rid,
            action,
        )
        return {
            "status": "restricted",
            "tool": action,
            "args": payload,
            "policy": spec.policy.value,
            "message": _RESTRICTED_MESSAGE,
        }

    if spec.policy == ToolPolicy.APPROVAL_REQUIRED:
        if not spec.allow_deferred_execution:
            logger.info(
                "jarvis.executor.deferred_execution_not_allowed run_id=%s tool=%s",
                rid,
                action,
            )
            return {
                "status": "deferred_execution_not_allowed",
                "tool": action,
                "policy": spec.policy.value,
                "message": "This tool is not enabled for the deferred approval and execution pipeline.",
            }
        if not tool_allowed_for_current_env(spec):
            logger.info(
                "jarvis.executor.environment_not_allowed run_id=%s tool=%s env=%s",
                rid,
                action,
                get_jarvis_env(),
            )
            return environment_not_allowed_result(action, spec)
        created_at = utc_now_iso()
        run_key = (rid or "").strip()
        result: dict[str, Any] = {
            "status": "approval_required",
            "jarvis_run_id": run_key,
            "tool": action,
            "args": payload,
            "policy": spec.policy.value,
            "category": spec.category.value,
            "message": _APPROVAL_MESSAGE,
            "created_at": created_at,
        }
        if run_key:
            get_default_approval_storage().record_pending(
                build_pending_approval_record(
                    jarvis_run_id=run_key,
                    tool=action,
                    args=payload,
                    policy=spec.policy.value,
                    category=spec.category.value,
                    message=_APPROVAL_MESSAGE,
                    created_at=created_at,
                    risk_level=spec.risk_level.value,
                    allowed_envs=sorted(spec.allowed_envs),
                )
            )
        else:
            logger.warning(
                "jarvis.executor.approval_required_no_run_id tool=%s (record not stored)",
                action,
            )
        logger.info(
            "jarvis.executor.approval_required run_id=%s tool=%s",
            rid,
            action,
        )
        return result

    if spec.policy not in EXECUTABLE_POLICIES:
        logger.warning(
            "jarvis.executor.policy_denied run_id=%s action=%s policy=%s",
            rid,
            action,
            spec.policy.value,
        )
        return {
            "error": "policy_denied",
            "action": action,
            "policy": spec.policy.value,
        }

    logger.info(
        "jarvis.executor.invoke run_id=%s action=%s policy=%s",
        rid,
        action,
        spec.policy.value,
    )

    return invoke_registered_tool(action, args, jarvis_run_id=jarvis_run_id)


def invoke_registered_tool(
    tool_name: str,
    args: dict[str, Any],
    *,
    jarvis_run_id: str | None = None,
) -> Any:
    """
    Resolve tool by name, validate ``args`` with its Pydantic schema, call ``fn``.

    No planner and no policy checks — used by :func:`execute_plan` (after policy
    allows) and by manual ``execute_ready_action`` (after approval storage gates).
    Returns the tool return value, or a structured ``{"error": ...}`` dict on failure.
    """
    rid = (jarvis_run_id or "").strip() or None
    name = (tool_name or "").strip()
    spec = get_tool_spec(name)
    if spec is None:
        logger.warning("invoke_registered_tool unknown_tool run_id=%s tool=%r", rid, name)
        return {"error": "unknown_tool", "action": name}

    try:
        validated_args = spec.args_model.model_validate(args)
    except Exception as e:
        logger.warning(
            "invoke_registered_tool args_invalid run_id=%s action=%s err=%s",
            rid,
            name,
            e,
        )
        return {
            "error": "args_invalid",
            "action": name,
            "detail": str(e),
        }

    payload = validated_args.model_dump()

    if not tool_allowed_for_current_env(spec):
        logger.info(
            "invoke_registered_tool environment_not_allowed run_id=%s tool=%s env=%s",
            rid,
            name,
            get_jarvis_env(),
        )
        return environment_not_allowed_result(name, spec)

    if name == "execute_marketing_proposal":
        from app.jarvis.marketing_adapter import safe_execute_marketing_proposal

        proposal = payload.get("proposal")
        if not isinstance(proposal, dict):
            return {
                "error": "args_invalid",
                "action": name,
                "detail": "proposal must be a dict",
            }
        logger.info(
            "jarvis.invoke_registered_tool.execute_marketing_proposal run_id=%s",
            rid,
        )
        return safe_execute_marketing_proposal(proposal)

    try:
        result = spec.fn(**payload)
    except TypeError as e:
        logger.warning("invoke_registered_tool tool_type_error run_id=%s action=%s err=%s", rid, name, e)
        return {"error": "tool_failed", "action": name, "detail": str(e)}
    except Exception as e:
        logger.warning("invoke_registered_tool tool_failed run_id=%s action=%s err=%s", rid, name, e)
        return {"error": "tool_failed", "action": name, "detail": str(e)}

    logger.info("invoke_registered_tool success run_id=%s action=%s", rid, name)
    return result


def is_invoke_error_payload(value: Any) -> bool:
    """True if :func:`invoke_registered_tool` returned a structured failure dict."""
    return isinstance(value, dict) and value.get("error") in (
        "unknown_tool",
        "args_invalid",
        "tool_failed",
    )
