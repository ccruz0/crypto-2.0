"""Registered tools for Jarvis with argument schemas and policy metadata."""

from __future__ import annotations

import logging
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from app.jarvis.approval_storage import get_default_approval_storage
from app.jarvis.marketing_schemas import (
    AnalyzeMarketingOpportunitiesArgs,
    ExecuteMarketingProposalArgs,
    MarketingAnalysisWindowArgs,
    ProposeMarketingActionsArgs,
    RunMarketingReviewArgs,
    StageMarketingActionForApprovalArgs,
    TopPagesByConversionArgs,
)
from app.jarvis.perico_tools import perico_apply_patch as perico_apply_patch_impl
from app.jarvis.perico_tools import perico_repo_read as perico_repo_read_impl
from app.jarvis.perico_tools import perico_run_pytest as perico_run_pytest_impl
from app.jarvis.marketing_tools import (
    analyze_marketing_opportunities,
    execute_marketing_proposal,
    get_ga4_booking_funnel,
    get_google_ads_summary,
    get_search_console_summary,
    get_top_pages_by_conversion,
    list_marketing_tools_status,
    propose_marketing_actions,
    run_marketing_review,
    stage_marketing_action_for_approval,
)

logger = logging.getLogger(__name__)


class ToolPolicy(str, Enum):
    """Execution policy for tools (future: approval flows, trading)."""

    SAFE = "safe"
    APPROVAL_REQUIRED = "approval_required"
    RESTRICTED = "restricted"


class ToolCategory(str, Enum):
    """High-level category for routing, UI, and future policy rules."""

    READ = "read"
    WRITE = "write"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    TRADING = "trading"


# Policies the executor may run without human approval (extend deliberately).
EXECUTABLE_POLICIES: frozenset[ToolPolicy] = frozenset({ToolPolicy.SAFE})

# Jarvis environment names (see ``app.jarvis.runtime_env.get_jarvis_env``).
ALL_JARVIS_ENVS: frozenset[str] = frozenset({"dev", "lab", "prod"})
DEV_LAB_JARVIS_ENVS: frozenset[str] = frozenset({"dev", "lab"})


class ToolRiskLevel(str, Enum):
    """Explicit operational risk (not derived from policy or category)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _default_allowed_envs() -> frozenset[str]:
    return ALL_JARVIS_ENVS


class EmptyArgs(BaseModel):
    """No parameters (empty object only)."""

    model_config = ConfigDict(extra="forbid")


class EchoMessageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = ""


class SendTestNotificationArgs(BaseModel):
    """Placeholder args for approval-flow testing (no real send)."""

    model_config = ConfigDict(extra="forbid")

    channel: str = "test"
    note: str = ""


class ListPendingApprovalsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)


class GetApprovalStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jarvis_run_id: str = Field(..., min_length=1, max_length=128)


class ListRecentApprovalsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)


class ListReadyForExecutionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)


class ApproveRejectPendingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jarvis_run_id: str = Field(..., min_length=1, max_length=128)
    reason: str = Field(default="", max_length=4000)
    actor: str = Field(default="", max_length=256)


class ExecuteReadyActionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jarvis_run_id: str = Field(..., min_length=1, max_length=128)
    actor: str = Field(default="", max_length=256)


class PericoRepoReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = Field(..., description="list | read | grep")
    relative_path: str = Field(default="", max_length=1024)
    pattern: str = Field(default="", max_length=512)
    max_results: int = Field(default=80, ge=1, le=200)


class PericoApplyPatchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_path: str = Field(..., min_length=1, max_length=1024)
    old_text: str = Field(..., min_length=1, max_length=50_000)
    new_text: str = Field(default="", max_length=50_000)


class PericoRunPytestArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_path: str = Field(default="", max_length=1024)
    extra_args: str = Field(default="", max_length=512)
    timeout_seconds: int = Field(default=180, ge=15, le=900)


ToolFn = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: ToolFn
    args_model: type[BaseModel]
    policy: ToolPolicy
    description: str
    category: ToolCategory
    allow_deferred_execution: bool = False
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    allowed_envs: frozenset[str] = field(default_factory=_default_allowed_envs)


def get_server_time(**kwargs: Any) -> dict[str, Any]:
    """Return current server time in UTC (ISO 8601) and unix float."""
    _ = kwargs
    now = datetime.now(timezone.utc)
    return {
        "iso_utc": now.isoformat(),
        "unix": now.timestamp(),
    }


def get_unix_time(**kwargs: Any) -> dict[str, Any]:
    """Return integer unix timestamp and UTC ISO string."""
    _ = kwargs
    now = datetime.now(timezone.utc)
    return {"unix": int(now.timestamp()), "iso_utc": now.isoformat()}


def echo_message(**kwargs: Any) -> dict[str, Any]:
    """Echo the given message (for testing and simple replies)."""
    args = EchoMessageArgs.model_validate(kwargs)
    return {"echo": args.message.strip()}


def get_server_status(**kwargs: Any) -> dict[str, Any]:
    """Lightweight process snapshot (no DB)."""
    _ = kwargs
    return {
        "status": "ok",
        "component": "jarvis",
        "python": sys.version.split()[0],
        "platform": platform.system(),
    }


def send_test_notification(**kwargs: Any) -> dict[str, Any]:
    """
    Placeholder side-effect tool (no external I/O). Executor path still defers until
    approval; manual execution uses :func:`execute_ready_action`.
    """
    args = SendTestNotificationArgs.model_validate(kwargs)
    return {
        "dry_run": True,
        "channel": args.channel,
        "note": args.note,
    }


def restricted_operation_placeholder(**kwargs: Any) -> dict[str, Any]:
    """Reserved for future restricted flows; must not execute via executor."""
    _ = EmptyArgs.model_validate(kwargs)
    raise RuntimeError("restricted_operation_placeholder must not execute")


def deferred_pipeline_blocked(**kwargs: Any) -> dict[str, Any]:
    """Test hook: approval_required but not eligible for deferred pipeline."""
    _ = EmptyArgs.model_validate(kwargs)
    raise RuntimeError("deferred_pipeline_blocked must not execute")


def list_available_tools(**kwargs: Any) -> dict[str, Any]:
    """List registered tools with policy, category, and description."""
    _ = kwargs
    tools: list[dict[str, Any]] = []
    for name in sorted(TOOL_SPECS.keys()):
        spec = TOOL_SPECS[name]
        tools.append(
            {
                "name": name,
                "description": spec.description,
                "policy": spec.policy.value,
                "category": spec.category.value,
                "allow_deferred_execution": spec.allow_deferred_execution,
                "risk_level": spec.risk_level.value,
                "allowed_envs": sorted(spec.allowed_envs),
            }
        )
    return {"tools": tools}


def list_pending_approvals(**kwargs: Any) -> dict[str, Any]:
    """Return newest rows still pending human approval (includes ``execution_status``)."""
    args = ListPendingApprovalsArgs.model_validate(kwargs)
    rows = get_default_approval_storage().list_pending(limit=args.limit)
    return {
        "status": "ok",
        "approvals": rows,
        "count": len(rows),
    }


def list_recent_approvals(**kwargs: Any) -> dict[str, Any]:
    """Return newest rows in any approval state (includes ``execution_status``)."""
    args = ListRecentApprovalsArgs.model_validate(kwargs)
    rows = get_default_approval_storage().list_recent(limit=args.limit)
    return {
        "status": "ok",
        "approvals": rows,
        "count": len(rows),
    }


def list_ready_for_execution(**kwargs: Any) -> dict[str, Any]:
    """Return approved rows ready for deferred execution (does not run tools)."""
    args = ListReadyForExecutionArgs.model_validate(kwargs)
    rows = get_default_approval_storage().list_ready_for_execution(limit=args.limit)
    return {
        "status": "ok",
        "approvals": rows,
        "count": len(rows),
    }


def get_approval_status(**kwargs: Any) -> dict[str, Any]:
    """Look up one row by ``jarvis_run_id`` (includes ``approval_status`` and ``execution_status``)."""
    args = GetApprovalStatusArgs.model_validate(kwargs)
    rid = args.jarvis_run_id.strip()
    rec = get_default_approval_storage().get_by_run_id(rid)
    if rec is None:
        return {
            "found": False,
            "status": "not_found",
            "jarvis_run_id": rid,
            "message": "No approval record for this jarvis_run_id.",
        }
    return {"found": True, "status": "ok", "approval": rec}


def _approve_or_reject(
    *,
    approve: bool,
    jarvis_run_id: str,
    reason: str,
    actor: str = "",
) -> dict[str, Any]:
    store = get_default_approval_storage()
    rid = jarvis_run_id.strip()
    actor_clean = (actor or "").strip() or None
    if approve:
        rec, err = store.approve_by_run_id(
            rid,
            reason=reason or None,
            approved_by=actor_clean,
        )
    else:
        rec, err = store.reject_by_run_id(
            rid,
            reason=reason or None,
            rejected_by=actor_clean,
        )
    if err == "not_found":
        return {
            "status": "not_found",
            "jarvis_run_id": rid,
            "message": "No approval record for this jarvis_run_id.",
        }
    if err == "already_decided":
        existing = store.get_by_run_id(rid)
        return {
            "status": "already_decided",
            "jarvis_run_id": rid,
            "approval_status": (existing or {}).get("approval_status"),
            "execution_status": (existing or {}).get("execution_status"),
            "approval": existing,
            "message": "This approval was already decided.",
        }
    assert rec is not None
    logger.info(
        "jarvis.approval.decision jarvis_run_id=%s approval_status=%s tool=%s approve=%s",
        rid,
        rec.get("approval_status"),
        rec.get("tool"),
        approve,
    )
    return {
        "status": "ok",
        "jarvis_run_id": rid,
        "approval_status": rec.get("approval_status"),
        "execution_status": rec.get("execution_status"),
        "approval": rec,
        "created_at": rec.get("created_at"),
        "updated_at": rec.get("updated_at"),
        "decision": rec.get("decision"),
        "decision_reason": rec.get("decision_reason"),
    }


def approve_pending_action(**kwargs: Any) -> dict[str, Any]:
    """Mark a pending approval as approved (storage only; does not run tools)."""
    args = ApproveRejectPendingArgs.model_validate(kwargs)
    return _approve_or_reject(
        approve=True,
        jarvis_run_id=args.jarvis_run_id,
        reason=args.reason,
        actor=args.actor,
    )


def reject_pending_action(**kwargs: Any) -> dict[str, Any]:
    """Mark a pending approval as rejected (storage only)."""
    args = ApproveRejectPendingArgs.model_validate(kwargs)
    return _approve_or_reject(
        approve=False,
        jarvis_run_id=args.jarvis_run_id,
        reason=args.reason,
        actor=args.actor,
    )


def perico_repo_read(**kwargs: Any) -> dict[str, Any]:
    """Perico: list/read/grep under PERICO_REPO_ROOT (default crypto-2.0)."""
    args = PericoRepoReadArgs.model_validate(kwargs)
    op = (args.operation or "").strip().lower()
    if op not in ("list", "read", "grep"):
        return {"ok": False, "error": "invalid_operation", "allowed": ["list", "read", "grep"]}
    return perico_repo_read_impl(
        operation=op,
        relative_path=args.relative_path,
        pattern=args.pattern,
        max_results=args.max_results,
    )


def perico_apply_patch(**kwargs: Any) -> dict[str, Any]:
    """Perico: single-occurrence UTF-8 text replace (requires PERICO_WRITE_ENABLED)."""
    args = PericoApplyPatchArgs.model_validate(kwargs)
    return perico_apply_patch_impl(
        relative_path=args.relative_path,
        old_text=args.old_text,
        new_text=args.new_text,
    )


def perico_run_pytest(**kwargs: Any) -> dict[str, Any]:
    """Perico: run pytest under repo backend/ (cwd); optional path and extra args."""
    args = PericoRunPytestArgs.model_validate(kwargs)
    return perico_run_pytest_impl(
        relative_path=args.relative_path,
        extra_args=args.extra_args,
        timeout_seconds=args.timeout_seconds,
    )


def execute_ready_action(**kwargs: Any) -> dict[str, Any]:
    """
    Run the stored tool once for an approved + ready row (manual; no automation).
    """
    from app.jarvis.approval_storage import (
        APPROVAL_APPROVED,
        EXEC_EXECUTED,
        EXEC_FAILED,
        EXEC_READY,
    )
    from app.jarvis.executor import (
        environment_not_allowed_result,
        invoke_registered_tool,
        is_invoke_error_payload,
        tool_allowed_for_current_env,
    )

    args = ExecuteReadyActionArgs.model_validate(kwargs)
    rid = args.jarvis_run_id.strip()
    actor_clean = (args.actor or "").strip() or None
    store = get_default_approval_storage()
    rec = store.get_by_run_id(rid)
    if rec is None:
        return {"status": "not_found", "jarvis_run_id": rid}

    ap = (rec.get("approval_status") or rec.get("status") or "").strip()
    if ap != APPROVAL_APPROVED:
        return {"status": "not_approved", "jarvis_run_id": rid, "approval_status": ap}

    ex = (rec.get("execution_status") or "").strip()
    if ex == EXEC_EXECUTED:
        return {"status": "already_executed", "jarvis_run_id": rid}
    if ex == EXEC_FAILED:
        return {
            "status": "not_ready",
            "jarvis_run_id": rid,
            "current_execution_status": EXEC_FAILED,
            "message": "Execution already failed; manual retry is not enabled.",
        }
    if ex != EXEC_READY:
        return {
            "status": "not_ready",
            "jarvis_run_id": rid,
            "current_execution_status": ex or None,
        }

    tool_name = (rec.get("tool") or "").strip()
    tool_args = rec.get("args") if isinstance(rec.get("args"), dict) else {}

    exec_spec = get_tool_spec(tool_name)
    if exec_spec is None or not exec_spec.allow_deferred_execution:
        return {
            "status": "deferred_execution_not_allowed",
            "tool": tool_name,
            "jarvis_run_id": rid,
            "message": "This tool is not enabled for deferred manual execution.",
        }

    if not tool_allowed_for_current_env(exec_spec):
        out = environment_not_allowed_result(tool_name, exec_spec)
        return {**out, "jarvis_run_id": rid}

    if exec_spec.risk_level in (ToolRiskLevel.HIGH, ToolRiskLevel.CRITICAL):
        if not actor_clean:
            return {
                "status": "actor_required",
                "tool": tool_name,
                "risk_level": exec_spec.risk_level.value,
                "message": "Non-empty actor is required for high- and critical-risk manual execution.",
                "jarvis_run_id": rid,
            }

    raw = invoke_registered_tool(tool_name, tool_args, jarvis_run_id=rid)

    if isinstance(raw, dict) and raw.get("status") == "environment_not_allowed":
        return {**raw, "jarvis_run_id": rid}

    if is_invoke_error_payload(raw):
        err_detail = str((raw or {}).get("detail") or raw)
        fin, err = store.finalize_ready_execution(
            rid,
            success=False,
            execution_error=err_detail,
            executed_by=actor_clean,
        )
        if err == "already_executed":
            return {"status": "already_executed", "jarvis_run_id": rid}
        if err == "already_failed":
            return {
                "status": "not_ready",
                "jarvis_run_id": rid,
                "current_execution_status": EXEC_FAILED,
            }
        assert fin is not None
        return {
            "status": "ok",
            "jarvis_run_id": rid,
            "execution_status": fin.get("execution_status"),
            "executed_at": fin.get("executed_at"),
            "execution_error": fin.get("execution_error"),
            "approval": fin,
        }

    fin, err = store.finalize_ready_execution(
        rid,
        success=True,
        execution_result=raw,
        executed_by=actor_clean,
    )
    if err == "already_executed":
        return {"status": "already_executed", "jarvis_run_id": rid}
    if err == "already_failed":
        return {
            "status": "not_ready",
            "jarvis_run_id": rid,
            "current_execution_status": EXEC_FAILED,
        }
    assert fin is not None
    if tool_name == "execute_marketing_proposal":
        logger.info(
            "jarvis.marketing.manual_execution_complete jarvis_run_id=%s execution_status=%s",
            rid,
            fin.get("execution_status"),
        )
    return {
        "status": "ok",
        "jarvis_run_id": rid,
        "execution_status": fin.get("execution_status"),
        "executed_at": fin.get("executed_at"),
        "execution_result": fin.get("execution_result"),
        "approval": fin,
    }


TOOL_SPECS: dict[str, ToolSpec] = {
    "get_server_time": ToolSpec(
        name="get_server_time",
        fn=get_server_time,
        args_model=EmptyArgs,
        policy=ToolPolicy.SAFE,
        description="Current UTC time as ISO string and unix float.",
        category=ToolCategory.READ,
    ),
    "get_unix_time": ToolSpec(
        name="get_unix_time",
        fn=get_unix_time,
        args_model=EmptyArgs,
        policy=ToolPolicy.SAFE,
        description="Current unix timestamp (int) and UTC ISO string.",
        category=ToolCategory.READ,
    ),
    "get_server_status": ToolSpec(
        name="get_server_status",
        fn=get_server_status,
        args_model=EmptyArgs,
        policy=ToolPolicy.SAFE,
        description="Lightweight health snapshot (python version, platform).",
        category=ToolCategory.READ,
    ),
    "echo_message": ToolSpec(
        name="echo_message",
        fn=echo_message,
        args_model=EchoMessageArgs,
        policy=ToolPolicy.SAFE,
        description="Echo a message back (args: message string).",
        category=ToolCategory.WRITE,
    ),
    "list_available_tools": ToolSpec(
        name="list_available_tools",
        fn=list_available_tools,
        args_model=EmptyArgs,
        policy=ToolPolicy.SAFE,
        description="List tool names, policy, category, and short descriptions.",
        category=ToolCategory.READ,
    ),
    "list_pending_approvals": ToolSpec(
        name="list_pending_approvals",
        fn=list_pending_approvals,
        args_model=ListPendingApprovalsArgs,
        policy=ToolPolicy.SAFE,
        description="List pending approval records (optional args: limit, default 20, max 100).",
        category=ToolCategory.READ,
    ),
    "get_approval_status": ToolSpec(
        name="get_approval_status",
        fn=get_approval_status,
        args_model=GetApprovalStatusArgs,
        policy=ToolPolicy.SAFE,
        description="Get one approval record by jarvis_run_id (any state).",
        category=ToolCategory.READ,
    ),
    "list_recent_approvals": ToolSpec(
        name="list_recent_approvals",
        fn=list_recent_approvals,
        args_model=ListRecentApprovalsArgs,
        policy=ToolPolicy.SAFE,
        description="List recent approval rows in any state (optional limit, default 20).",
        category=ToolCategory.READ,
    ),
    "list_ready_for_execution": ToolSpec(
        name="list_ready_for_execution",
        fn=list_ready_for_execution,
        args_model=ListReadyForExecutionArgs,
        policy=ToolPolicy.SAFE,
        description="List approved rows with execution_status=ready (deferred run not performed here).",
        category=ToolCategory.READ,
    ),
    "approve_pending_action": ToolSpec(
        name="approve_pending_action",
        fn=approve_pending_action,
        args_model=ApproveRejectPendingArgs,
        policy=ToolPolicy.SAFE,
        description="Approve a pending action by jarvis_run_id (optional reason).",
        category=ToolCategory.WRITE,
    ),
    "reject_pending_action": ToolSpec(
        name="reject_pending_action",
        fn=reject_pending_action,
        args_model=ApproveRejectPendingArgs,
        policy=ToolPolicy.SAFE,
        description="Reject a pending action by jarvis_run_id (optional reason).",
        category=ToolCategory.WRITE,
    ),
    "execute_ready_action": ToolSpec(
        name="execute_ready_action",
        fn=execute_ready_action,
        args_model=ExecuteReadyActionArgs,
        policy=ToolPolicy.SAFE,
        description="Run one approved+ready deferred tool manually (jarvis_run_id).",
        category=ToolCategory.WRITE,
    ),
    "list_marketing_tools_status": ToolSpec(
        name="list_marketing_tools_status",
        fn=list_marketing_tools_status,
        args_model=EmptyArgs,
        policy=ToolPolicy.SAFE,
        description="Marketing Intelligence: GSC/GA4/Google Ads/site configuration readiness (Peluquería Cruz).",
        category=ToolCategory.READ,
    ),
    "get_search_console_summary": ToolSpec(
        name="get_search_console_summary",
        fn=get_search_console_summary,
        args_model=MarketingAnalysisWindowArgs,
        policy=ToolPolicy.SAFE,
        description="Marketing Intelligence: compact SEO summary (top queries/pages, clicks, impressions, CTR, position).",
        category=ToolCategory.READ,
    ),
    "get_ga4_booking_funnel": ToolSpec(
        name="get_ga4_booking_funnel",
        fn=get_ga4_booking_funnel,
        args_model=MarketingAnalysisWindowArgs,
        policy=ToolPolicy.SAFE,
        description="Marketing Intelligence: GA4 booking/conversion funnel snapshot (read-only).",
        category=ToolCategory.READ,
    ),
    "get_google_ads_summary": ToolSpec(
        name="get_google_ads_summary",
        fn=get_google_ads_summary,
        args_model=MarketingAnalysisWindowArgs,
        policy=ToolPolicy.SAFE,
        description="Marketing Intelligence: Google Ads SEM summary (spend, clicks, conversions, CPC/CPA when available).",
        category=ToolCategory.READ,
    ),
    "get_top_pages_by_conversion": ToolSpec(
        name="get_top_pages_by_conversion",
        fn=get_top_pages_by_conversion,
        args_model=TopPagesByConversionArgs,
        policy=ToolPolicy.SAFE,
        description="Marketing Intelligence: strongest/weakest landing pages by conversion behavior (GA4).",
        category=ToolCategory.READ,
    ),
    "analyze_marketing_opportunities": ToolSpec(
        name="analyze_marketing_opportunities",
        fn=analyze_marketing_opportunities,
        args_model=AnalyzeMarketingOpportunitiesArgs,
        policy=ToolPolicy.SAFE,
        description="Marketing Intelligence: deterministic SEO/SEM/GA4 opportunity synthesis for Peluquería Cruz (read-only).",
        category=ToolCategory.READ,
    ),
    "propose_marketing_actions": ToolSpec(
        name="propose_marketing_actions",
        fn=propose_marketing_actions,
        args_model=ProposeMarketingActionsArgs,
        policy=ToolPolicy.SAFE,
        description="Marketing Intelligence: deterministic proposed actions from opportunity analysis (read-only; no execution).",
        category=ToolCategory.READ,
    ),
    "run_marketing_review": ToolSpec(
        name="run_marketing_review",
        fn=run_marketing_review,
        args_model=RunMarketingReviewArgs,
        policy=ToolPolicy.SAFE,
        description=(
            "Orchestration: run analyze → propose → optional staging in one pipeline "
            "(read-only analysis; staging uses internal approval store only)."
        ),
        category=ToolCategory.READ,
    ),
    "stage_marketing_action_for_approval": ToolSpec(
        name="stage_marketing_action_for_approval",
        fn=stage_marketing_action_for_approval,
        args_model=StageMarketingActionForApprovalArgs,
        policy=ToolPolicy.SAFE,
        description="Marketing Intelligence: stage selected proposed actions into pending Jarvis approvals (no execution).",
        category=ToolCategory.WRITE,
    ),
    "execute_marketing_proposal": ToolSpec(
        name="execute_marketing_proposal",
        fn=execute_marketing_proposal,
        args_model=ExecuteMarketingProposalArgs,
        policy=ToolPolicy.APPROVAL_REQUIRED,
        description="Marketing: execute approved proposal (simulated; requires approval + manual execute_ready_action).",
        category=ToolCategory.EXTERNAL_SIDE_EFFECT,
        allow_deferred_execution=True,
        risk_level=ToolRiskLevel.MEDIUM,
        allowed_envs=ALL_JARVIS_ENVS,
    ),
    "deferred_pipeline_blocked": ToolSpec(
        name="deferred_pipeline_blocked",
        fn=deferred_pipeline_blocked,
        args_model=EmptyArgs,
        policy=ToolPolicy.APPROVAL_REQUIRED,
        description="Test hook: approval_required but blocked from deferred approval/execute pipeline.",
        category=ToolCategory.WRITE,
        allow_deferred_execution=False,
        risk_level=ToolRiskLevel.MEDIUM,
        allowed_envs=ALL_JARVIS_ENVS,
    ),
    "send_test_notification": ToolSpec(
        name="send_test_notification",
        fn=send_test_notification,
        args_model=SendTestNotificationArgs,
        policy=ToolPolicy.APPROVAL_REQUIRED,
        description="Placeholder notification (does not send; requires approval to run).",
        category=ToolCategory.EXTERNAL_SIDE_EFFECT,
        allow_deferred_execution=True,
        risk_level=ToolRiskLevel.MEDIUM,
        allowed_envs=DEV_LAB_JARVIS_ENVS,
    ),
    "restricted_operation_placeholder": ToolSpec(
        name="restricted_operation_placeholder",
        fn=restricted_operation_placeholder,
        args_model=EmptyArgs,
        policy=ToolPolicy.RESTRICTED,
        description="Placeholder for restricted operations (always denied by executor).",
        category=ToolCategory.TRADING,
        risk_level=ToolRiskLevel.CRITICAL,
        allowed_envs=ALL_JARVIS_ENVS,
    ),
    "perico_repo_read": ToolSpec(
        name="perico_repo_read",
        fn=perico_repo_read,
        args_model=PericoRepoReadArgs,
        policy=ToolPolicy.SAFE,
        description=(
            "Perico: read-only repo access — list directory, read text file, or grep simple pattern "
            "(paths confined to PERICO_REPO_ROOT)."
        ),
        category=ToolCategory.READ,
        allowed_envs=ALL_JARVIS_ENVS,
    ),
    "perico_apply_patch": ToolSpec(
        name="perico_apply_patch",
        fn=perico_apply_patch,
        args_model=PericoApplyPatchArgs,
        policy=ToolPolicy.SAFE,
        description=(
            "Perico: apply minimal single-occurrence text patch (UTF-8). "
            "Requires PERICO_WRITE_ENABLED=1; paths confined to PERICO_REPO_ROOT."
        ),
        category=ToolCategory.WRITE,
        risk_level=ToolRiskLevel.MEDIUM,
        allowed_envs=ALL_JARVIS_ENVS,
    ),
    "perico_run_pytest": ToolSpec(
        name="perico_run_pytest",
        fn=perico_run_pytest,
        args_model=PericoRunPytestArgs,
        policy=ToolPolicy.SAFE,
        description=(
            "Perico: run pytest -q from repo backend/ (or repo root if no backend/). "
            "Optional relative_path (tests file or dir) and extra_args."
        ),
        category=ToolCategory.READ,
        allowed_envs=ALL_JARVIS_ENVS,
    ),
}

# Back-compat: name -> callable
TOOL_REGISTRY: dict[str, ToolFn] = {k: v.fn for k, v in TOOL_SPECS.items()}


def list_tool_names() -> list[str]:
    return sorted(TOOL_SPECS.keys())


def get_tool_spec(name: str) -> ToolSpec | None:
    return TOOL_SPECS.get(name.strip())
