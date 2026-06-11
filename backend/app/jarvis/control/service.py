"""Jarvis Control Center service layer (status, task visibility, Builder prepare stub)."""

from __future__ import annotations

from typing import Any

from app.core.environment import (
    getRuntimeEnv,
    is_atp_trading_only,
    is_jarvis_builder_allowed,
    is_jarvis_control_enabled,
)
from app.jarvis.control import persistence as jcp
from app.jarvis.control import workflow as builder_workflow
from app.jarvis.mvp.risk import classify_task_risk

_BUILDER_STUB_ARTIFACT_MESSAGE = (
    "Builder prepare stub created. Cursor bridge not invoked."
)
_BUILDER_STUB_RESPONSE_MESSAGE = (
    "Builder task created in stub mode. No execution occurred."
)


def _session_environment() -> str:
    return "prod" if getRuntimeEnv() == "aws" else "local"


def _prompt_summary(prompt: str, *, max_chars: int = 200) -> str:
    text = (prompt or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."


class JarvisControlService:
    """Control surface over persistence, environment gates, and Builder prepare stub."""

    def get_control_status(self) -> dict[str, Any]:
        control_enabled = is_jarvis_control_enabled()
        builder_allowed = is_jarvis_builder_allowed()
        trading_only = is_atp_trading_only()
        environment = getRuntimeEnv()
        builder_available = control_enabled and builder_allowed and not trading_only
        return {
            "control_enabled": control_enabled,
            "builder_allowed": builder_allowed,
            "trading_only": trading_only,
            "environment": environment,
            "builder_available": builder_available,
        }

    def list_recent_tasks(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return jcp.list_control_tasks(limit=limit)

    def get_task_detail(self, task_id: str) -> dict[str, Any] | None:
        return jcp.get_control_task(task_id)

    def prepare_builder_stub(
        self,
        *,
        prompt: str,
        domain: str = "software",
        requested_by: str = "dashboard",
    ) -> dict[str, Any]:
        """Create a queued Builder task and audit event without invoking execution."""
        normalized_domain = (domain or "software").strip().lower() or "software"
        actor = (requested_by or "dashboard").strip() or "dashboard"
        risk_level = classify_task_risk(prompt)
        session_env = _session_environment()
        prompt_summary = _prompt_summary(prompt)
        artifact = {
            "stub": True,
            "bridge_invoked": False,
            "governance_created": False,
            "message": _BUILDER_STUB_ARTIFACT_MESSAGE,
            "plan": {
                "summary": prompt_summary,
                "domain": normalized_domain,
                "risk_level": risk_level,
            },
            "artifacts": [],
            "next_action": "awaiting_builder_execution",
        }

        session_id = jcp.create_control_session(
            created_by=actor,
            default_mode="builder",
            environment=session_env,
            domain=normalized_domain,
            metadata={"source": "builder_prepare_stub", "requested_by": actor},
        )
        task_id = jcp.create_control_task(
            session_id=session_id,
            prompt=prompt,
            mode="builder",
            domain=normalized_domain,
            status="queued",
            risk_level=risk_level,
            dry_run=True,
            builder_artifact=artifact,
        )
        jcp.append_control_audit_event(
            "builder_prepare_stub_created",
            task_id=task_id,
            session_id=session_id,
            actor_type="human",
            actor_id=actor,
            environment=session_env,
            payload={
                "prompt_summary": _prompt_summary(prompt),
                "prompt_chars": len(prompt or ""),
                "domain": normalized_domain,
                "risk_level": risk_level,
                "requested_by": actor,
                "stub": True,
                "bridge_invoked": False,
                "governance_created": False,
                "control_enabled": is_jarvis_control_enabled(),
                "builder_allowed": is_jarvis_builder_allowed(),
                "trading_only": is_atp_trading_only(),
            },
        )

        return {
            "task_id": task_id,
            "status": "queued",
            "mode": "builder",
            "risk_level": risk_level,
            "stub": True,
            "message": _BUILDER_STUB_RESPONSE_MESSAGE,
        }

    def get_builder_task(self, task_id: str) -> dict[str, Any] | None:
        return builder_workflow.get_builder_task_detail(task_id)

    def get_builder_timeline(self, task_id: str) -> list[dict[str, Any]] | None:
        return builder_workflow.get_builder_timeline(task_id)

    def list_builder_approvals(self, task_id: str) -> list[dict[str, Any]] | None:
        context = jcp.get_builder_workflow_context(task_id)
        if context is None:
            return None
        return context["approvals"]
