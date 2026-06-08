"""
Shared MVP repo staging worker (verify_clone only).

Used by ``backend/scripts/bedrock_repo_worker_mvp.py`` and the Jarvis tool
``repo_worker_verify_clone``. Subprocess work stays inside ``cursor_execution_bridge``.

Jarvis tool path: always refuses when ``ATP_TRADING_ONLY=1`` (no override).
Manual script path: may set ``BEDROCK_REPO_WORKER_ALLOW_IN_TRADING_ONLY=1`` for emergency tests only.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

MVP_ARTIFACT_VERSION = 1
MVP_JOB_KIND_VERIFY_CLONE = "verify_clone"

_ENV_ALLOW_IN_TRADING_ONLY = "BEDROCK_REPO_WORKER_ALLOW_IN_TRADING_ONLY"


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def assert_not_trading_only_unless_override() -> None:
    """Fail closed in trading-only mode unless explicit test override (manual script only)."""
    from app.core.environment import is_atp_trading_only

    if not is_atp_trading_only():
        return
    if _truthy_env(_ENV_ALLOW_IN_TRADING_ONLY):
        logger.warning(
            "%s=1 — bedrock_repo_worker_mvp allowed to run despite ATP_TRADING_ONLY (testing only)",
            _ENV_ALLOW_IN_TRADING_ONLY,
        )
        return
    raise SystemExit(
        "bedrock_repo_worker_mvp: refused (ATP_TRADING_ONLY=1). "
        "Run only on LAB or non-trading-only backends. "
        f"For emergency structural tests only, set {_ENV_ALLOW_IN_TRADING_ONLY}=1."
    )


def repo_worker_refused_reason_for_jarvis_tool() -> str | None:
    """
    Jarvis tool must never run repo worker on trading-only hosts, regardless of
    ``BEDROCK_REPO_WORKER_ALLOW_IN_TRADING_ONLY`` (that override is script-only).
    """
    from app.core.environment import is_atp_trading_only

    if is_atp_trading_only():
        return (
            "repo_worker_verify_clone is disabled when ATP_TRADING_ONLY=1 "
            "(trading-only process). Use LAB or unset ATP_TRADING_ONLY."
        )
    return None


def sanitize_correlation_id(raw: str) -> str:
    """Filesystem-safe id for staging dir (similar spirit to cursor bridge lock naming)."""
    s = (raw or "").strip()
    if not s:
        return "mvp-unknown"
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", s).strip("_")[:120]
    return safe or "mvp-unknown"


def validate_mvp_job(data: Any) -> dict[str, Any]:
    """
    Minimal schema: version int == 1, job_kind == verify_clone, correlation_id non-empty str.
    Returns a normalized dict; raises ValueError on invalid input.
    """
    if not isinstance(data, dict):
        raise ValueError("job must be a JSON object")
    ver = data.get("version")
    if ver != MVP_ARTIFACT_VERSION:
        raise ValueError(f"version must be {MVP_ARTIFACT_VERSION}")
    kind = (data.get("job_kind") or "").strip()
    if kind != MVP_JOB_KIND_VERIFY_CLONE:
        raise ValueError(f"job_kind must be {MVP_JOB_KIND_VERIFY_CLONE!r}")
    cid = data.get("correlation_id")
    if not isinstance(cid, str) or not cid.strip():
        raise ValueError("correlation_id must be a non-empty string")
    return {
        "version": MVP_ARTIFACT_VERSION,
        "job_kind": kind,
        "correlation_id": cid.strip(),
    }


def mvp_result_to_sections(artifact: dict[str, Any]) -> dict[str, str]:
    """Sections dict compatible with OpenClaw/Telegram summary style keys."""
    status = str(artifact.get("result_status") or "unknown")
    tests = artifact.get("tests") or {}
    diff = artifact.get("diff") or {}
    risks = artifact.get("risk_notes") or []
    rec = str(artifact.get("recommendation") or "").strip()

    test_summary = str(tests.get("summary") or "").strip() or "(no test summary)"
    diff_path = diff.get("path")
    diff_len = diff.get("byte_len")
    diff_excerpt = str(diff.get("excerpt") or "").strip()

    task_summary = (
        f"MVP verify_clone: status={status}. Tests: {test_summary[:400]}"
    )
    if diff_path:
        task_summary += f" Diff file: {diff_path} ({diff_len} bytes)."

    risk_level = "medium" if status != "ok" else "low"
    if risks:
        risk_level = f"{risk_level}; notes: {'; '.join(str(r) for r in risks)[:200]}"

    affected = "(none)"
    if diff_excerpt:
        lines = [ln.strip() for ln in diff_excerpt.splitlines() if ln.strip()][:8]
        affected = "\n".join(lines) if lines else "(diff excerpt empty)"

    recommended = rec or (
        "Review JSON artifact; re-run with correlation_id if tests failed."
        if status != "ok"
        else "Staging verify passed; optional next: integrate with approval flow (future)."
    )

    return {
        "Task Summary": task_summary[:2000],
        "Risk Level": risk_level[:500],
        "Affected Files": affected[:2000],
        "Recommended Fix": recommended[:2000],
    }


def build_mvp_artifact(
    *,
    job: dict[str, Any],
    staging_path: str | None,
    tests: dict[str, Any] | None,
    diff_info: dict[str, Any],
    result_status: str,
    risk_notes: list[str],
    recommendation: str,
    error: str | None = None,
) -> dict[str, Any]:
    """Stable top-level artifact shape for this MVP."""
    tests = tests or {}
    parts: list[str] = []
    if "backend_ok" in tests:
        parts.append(f"backend_ok={tests.get('backend_ok')}")
    if "frontend_ok" in tests:
        parts.append(f"frontend_ok={tests.get('frontend_ok')}")
    if "all_ok" in tests:
        parts.append(f"all_ok={tests.get('all_ok')}")
    test_summary = "; ".join(parts) if parts else str(tests.get("summary") or "")
    bex = str(tests.get("backend_output") or "")
    fex = str(tests.get("frontend_output") or "")

    return {
        "version": MVP_ARTIFACT_VERSION,
        "correlation_id": job["correlation_id"],
        "job_kind": job["job_kind"],
        "staging_path": staging_path,
        "tests": {
            "backend_ok": tests.get("backend_ok"),
            "frontend_ok": tests.get("frontend_ok"),
            "all_ok": tests.get("all_ok"),
            "summary": test_summary,
            "backend_output_excerpt": bex[:1500],
            "frontend_output_excerpt": fex[:1500],
        },
        "diff": diff_info,
        "result_status": result_status,
        "risk_notes": list(risk_notes),
        "recommendation": recommendation,
        "error": error,
    }


def run_verify_clone_job(
    job: dict[str, Any],
    *,
    keep_staging: bool = False,
) -> dict[str, Any]:
    """Execute verify_clone using cursor_execution_bridge only."""
    from app.services.cursor_execution_bridge import (
        capture_diff,
        cleanup_staging,
        provision_staging_workspace,
        run_tests_in_staging,
    )

    correlation = job["correlation_id"]
    task_id = sanitize_correlation_id(correlation)
    risk_notes: list[str] = [
        "MVP: verify_clone only; no patch apply, no Cursor CLI, no PR.",
        "Subprocess scope: bridge run_tests_in_staging / git diff only.",
    ]
    if _truthy_env(_ENV_ALLOW_IN_TRADING_ONLY):
        risk_notes.append(f"{_ENV_ALLOW_IN_TRADING_ONLY}=1 was set (trading-only override).")

    staging = provision_staging_workspace(task_id)
    if not staging:
        return build_mvp_artifact(
            job=job,
            staging_path=None,
            tests=None,
            diff_info={"captured": False, "path": None, "byte_len": 0, "excerpt": ""},
            result_status="error",
            risk_notes=risk_notes,
            recommendation="Fix staging provision (disk, git clone, ATP_STAGING_ROOT) and retry.",
            error="provision_staging_workspace returned None",
        )

    staging_path = str(staging.resolve())
    try:
        tests_out = run_tests_in_staging(staging, task_id=task_id)
        diff_path_obj = capture_diff(staging, task_id)
        diff_content = ""
        if diff_path_obj and diff_path_obj.is_file():
            try:
                diff_content = diff_path_obj.read_text(encoding="utf-8", errors="replace")
            except OSError:
                diff_content = ""

        diff_info: dict[str, Any] = {
            "captured": bool(diff_path_obj),
            "path": str(diff_path_obj) if diff_path_obj else None,
            "byte_len": len(diff_content.encode("utf-8")) if diff_content else 0,
            "excerpt": diff_content[:4000] if diff_content else "",
        }

        all_ok = bool(tests_out.get("all_ok"))
        result_status = "ok" if all_ok else "failed"
        recommendation = (
            "Tests passed in staging clone; safe to proceed with future integration steps."
            if all_ok
            else "Inspect tests.backend_output / tests in artifact; fix code and re-run."
        )
        err = None if all_ok else "tests reported all_ok=false"

        return build_mvp_artifact(
            job=job,
            staging_path=staging_path,
            tests=tests_out,
            diff_info=diff_info,
            result_status=result_status,
            risk_notes=risk_notes,
            recommendation=recommendation,
            error=err,
        )
    finally:
        if not keep_staging:
            cleanup_staging(task_id)


def jarvis_tool_result_from_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Narrow structured return for ``repo_worker_verify_clone`` Jarvis tool."""
    tests = artifact.get("tests") or {}
    diff = artifact.get("diff") or {}
    summary = (
        f"result_status={artifact.get('result_status')}; tests={tests.get('summary', '')}"
    )[:800]
    return {
        "tool": "repo_worker_verify_clone",
        "status": "completed",
        "result_status": artifact.get("result_status"),
        "summary": summary,
        "tests_summary": tests.get("summary"),
        "diff_summary": {
            "captured": diff.get("captured"),
            "path": diff.get("path"),
            "byte_len": diff.get("byte_len"),
            "excerpt_preview": (diff.get("excerpt") or "")[:800],
        },
        "risk_notes": list(artifact.get("risk_notes") or []),
        "sections": mvp_result_to_sections(artifact),
        "staging_path": artifact.get("staging_path"),
        "recommendation": artifact.get("recommendation"),
        "error": artifact.get("error"),
    }
