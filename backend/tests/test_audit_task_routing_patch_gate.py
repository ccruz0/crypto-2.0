"""Regression tests for full-system ATP audit routing and patch gate behavior."""

from app.services.agent_task_executor import infer_repo_area_for_task
from app.services.patch_proof import cursor_bridge_required_for_task


def _audit_task() -> dict:
    return {
        "id": "task-audit-1",
        "task": "Audit ATP codebase against documentation and business rules",
        "details": "Run a full-system audit and produce an investigation/report output only.",
        "type": "Bug",
        "project": "ATP",
    }


def test_full_atp_audit_not_narrowed_to_telegram_scope() -> None:
    area = infer_repo_area_for_task(_audit_task())
    assert area.get("area_name") == "ATP System-wide Audit"
    assert "telegram" not in [str(x).lower() for x in (area.get("matched_rules") or [])]


def test_audit_report_task_not_patch_gated_without_explicit_patch_request() -> None:
    required, reason = cursor_bridge_required_for_task(_audit_task(), "task-audit-1")
    assert required is False
    assert reason == "not_code_fix"

