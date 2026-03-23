"""
Versioning helpers for the agent task workflow.

Provides:
- semantic-like next-version suggestion (patch/minor/major)
- proposal summary builder for prepared tasks
- release marker that updates Notion metadata, appends changelog notes, and logs events
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services import path_guard

logger = logging.getLogger(__name__)

VERSION_STATUS_PROPOSED = "proposed"
VERSION_STATUS_APPROVED = "approved"
VERSION_STATUS_RELEASED = "released"
VERSION_STATUS_REJECTED = "rejected"

_CHANGE_TYPE_PATCH = "patch"
_CHANGE_TYPE_MINOR = "minor"
_CHANGE_TYPE_MAJOR = "major"


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _repo_root() -> Path:
    from app.services._paths import workspace_root
    return workspace_root()


def _looks_like_semver(value: str) -> bool:
    return bool(re.match(r"^\d+\.\d+\.\d+$", value or ""))


def _normalize_version(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("v"):
        raw = raw[1:]
    return raw


def _normalize_change_type(change_type: str) -> str:
    value = str(change_type or "").strip().lower()
    if value in (_CHANGE_TYPE_PATCH, _CHANGE_TYPE_MINOR, _CHANGE_TYPE_MAJOR):
        return value
    return _CHANGE_TYPE_PATCH


def _infer_change_type(prepared_task: dict[str, Any], analysis_result: dict[str, Any] | None = None) -> str:
    if isinstance(analysis_result, dict):
        explicit = str(analysis_result.get("change_type") or "").strip().lower()
        if explicit in (_CHANGE_TYPE_PATCH, _CHANGE_TYPE_MINOR, _CHANGE_TYPE_MAJOR):
            return explicit

    task = (prepared_task or {}).get("task") or {}
    title = str(task.get("task") or "").lower()
    task_type = str(task.get("type") or "").lower()
    details = str(task.get("details") or "").lower()
    blob = f"{title} {task_type} {details}"

    if any(k in blob for k in ("architecture", "core strategy", "core-strategy", "major refactor", "breaking")):
        return _CHANGE_TYPE_MAJOR
    if any(k in blob for k in ("improvement", "strategy", "logic", "behavior", "workflow")):
        return _CHANGE_TYPE_MINOR
    return _CHANGE_TYPE_PATCH


def _extract_current_version(task_obj: dict[str, Any]) -> str:
    direct = str(task_obj.get("current_version") or "").strip()
    if direct:
        return _normalize_version(direct)

    details = str(task_obj.get("details") or "")
    m = re.search(r"\bcurrent[_\s-]?version[:=\s]+v?(\d+\.\d+\.\d+)\b", details, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    return "0.1.0"


def suggest_next_version(current_version: str, change_type: str) -> str:
    """
    Suggest next semantic version by change type.

    Rules:
    - patch: x.y.z -> x.y.(z+1)
    - minor: x.y.z -> x.(y+1).0
    - major: x.y.z -> (x+1).0.0
    """
    normalized_version = _normalize_version(current_version)
    normalized_change = _normalize_change_type(change_type)

    if not _looks_like_semver(normalized_version):
        normalized_version = "0.1.0"

    major_s, minor_s, patch_s = normalized_version.split(".")
    major_i = int(major_s)
    minor_i = int(minor_s)
    patch_i = int(patch_s)

    if normalized_change == _CHANGE_TYPE_MAJOR:
        return f"{major_i + 1}.0.0"
    if normalized_change == _CHANGE_TYPE_MINOR:
        return f"{major_i}.{minor_i + 1}.0"
    return f"{major_i}.{minor_i}.{patch_i + 1}"


def build_version_summary(
    prepared_task: dict[str, Any],
    analysis_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build proposal metadata that can travel through task -> approval -> execution flow.
    """
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    execution_plan = list((prepared_task or {}).get("execution_plan") or [])

    current_version = _extract_current_version(task)
    change_type = _infer_change_type(prepared_task, analysis_result)
    proposed_version = suggest_next_version(current_version, change_type)

    analysis_summary = ""
    if isinstance(analysis_result, dict):
        analysis_summary = str(
            analysis_result.get("change_summary")
            or analysis_result.get("summary")
            or ""
        ).strip()

    if not analysis_summary:
        title = str(task.get("task") or "").strip() or "Untitled task"
        area_name = str(repo_area.get("area_name") or "").strip()
        area_suffix = f" in {area_name}" if area_name else ""
        analysis_summary = f"{title}{area_suffix}".strip()

    affected_files = list(repo_area.get("likely_files") or [])
    if isinstance(analysis_result, dict) and isinstance(analysis_result.get("affected_files"), list):
        affected_files = [str(x) for x in analysis_result.get("affected_files") if str(x).strip()]

    validation_plan = [s for s in execution_plan if isinstance(s, str) and ("validat" in s.lower() or "check" in s.lower())]
    if isinstance(analysis_result, dict) and isinstance(analysis_result.get("validation_plan"), list):
        validation_plan = [str(x) for x in analysis_result.get("validation_plan") if str(x).strip()]

    return {
        "current_version": current_version,
        "proposed_version": proposed_version,
        "approved_version": "",
        "released_version": "",
        "version_status": VERSION_STATUS_PROPOSED,
        "change_type": change_type,
        "change_summary": analysis_summary[:1000],
        "affected_files": affected_files[:30],
        "validation_plan": validation_plan[:20],
    }


def _append_release_changelog(
    *,
    task_id: str,
    version: str,
    summary: str,
) -> bool:
    """
    Append a lightweight release entry into docs/releases/CHANGELOG.md.
    """
    path = _repo_root() / "docs" / "releases" / "CHANGELOG.md"
    path_guard.safe_mkdir_lab(path.parent, context="agent_versioning:changelog_parent")

    if not path.exists():
        header = (
            "# Release Changelog\n\n"
            "Tracks OpenClaw agent-proposed business-logic improvements with version traceability.\n\n"
            "## Notion fields required for full traceability\n\n"
            "- `Current Version` (rich text or select)\n"
            "- `Proposed Version` (rich text or select)\n"
            "- `Approved Version` (rich text or select)\n"
            "- `Released Version` (rich text or select)\n"
            "- `Version Status` (select preferred: proposed, approved, released, rejected)\n"
            "- `Change Summary` (rich text)\n"
            "\n"
        )
        path_guard.safe_write_text(path, header, context="agent_versioning:changelog_header")

    date_str = _utc_date()
    block = (
        f"## v{version} - {date_str}\n\n"
        f"- Version: `v{version}`\n"
        f"- Date: `{date_str}`\n"
        f"- Task ID: `{task_id}`\n"
        f"- Summary: {summary.strip() or '(no summary provided)'}\n"
        "- Affected files: see task proposal metadata in Notion/agent activity log.\n"
        "- Validation note: recorded in task execution summary and Notion release comment.\n\n"
    )
    try:
        path_guard.safe_append_text(path, block, context="agent_versioning:changelog_append")
        return True
    except Exception as e:
        logger.warning("agent_versioning: changelog append failed %s", e)
        return False


def mark_version_released(task_id: str, released_version: str, summary: str) -> bool:
    """
    Mark a task version as released across Notion metadata + changelog + activity log.
    Returns True if Notion metadata update succeeded; still best-effort logs/changelog.
    """
    normalized_task_id = str(task_id or "").strip()
    normalized_version = _normalize_version(released_version)
    normalized_summary = str(summary or "").strip()
    if not normalized_task_id or not normalized_version:
        return False

    notion_ok = False
    try:
        from app.services.notion_tasks import update_notion_task_version_metadata

        comment = (
            f"Release note: v{normalized_version} released.\n"
            f"Summary: {normalized_summary or 'n/a'}"
        )
        notion_result = update_notion_task_version_metadata(
            page_id=normalized_task_id,
            metadata={
                "released_version": normalized_version,
                "version_status": VERSION_STATUS_RELEASED,
                "change_summary": normalized_summary,
            },
            append_comment=comment,
        )
        notion_ok = bool(notion_result.get("ok"))
    except Exception as e:
        logger.warning("agent_versioning: notion release metadata update failed %s", e)

    _append_release_changelog(
        task_id=normalized_task_id,
        version=normalized_version,
        summary=normalized_summary,
    )

    try:
        from app.services.agent_activity_log import log_agent_event

        log_agent_event(
            "version_released",
            task_id=normalized_task_id,
            details={
                "released_version": normalized_version,
                "version_status": VERSION_STATUS_RELEASED,
                "change_summary": normalized_summary,
            },
        )
    except Exception:
        pass
    return notion_ok
