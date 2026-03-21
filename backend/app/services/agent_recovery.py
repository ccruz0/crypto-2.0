"""
Autonomous recovery layer for the OpenClaw orchestration system.

Diagnoses and recovers from known low-risk orchestration failures without
human intervention. Approval gates for higher-risk actions are preserved.

Controlled by AGENT_RECOVERY_ENABLED env var. All recovery attempts are
logged to the agent activity log.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEPLOYING_STALE_MINUTES = 10
_PATCHING_STALE_MINUTES = 15
def _get_stale_in_progress_minutes() -> int:
    """Read AGENT_STALE_IN_PROGRESS_MINUTES env var (default 30)."""
    raw = (os.environ.get("AGENT_STALE_IN_PROGRESS_MINUTES") or "").strip()
    if raw:
        try:
            return max(5, min(1440, int(raw)))  # 5 min to 24h
        except ValueError:
            pass
    return 30


_IN_PROGRESS_STALE_MINUTES = 30  # fallback when env not used
_RECOVERY_EVENT_TYPE = "recovery_orphan_smoke_attempt"
_RECOVERY_REVALIDATE_EVENT_TYPE = "recovery_revalidate_patching_attempt"
_RECOVERY_MISSING_ARTIFACT_EVENT_TYPE = "recovery_missing_artifact_attempt"
_RECOVERY_STALE_IN_PROGRESS_EVENT_TYPE = "recovery_stale_in_progress_attempt"

# (save_subdir, file_prefix) for OpenClaw investigation artifacts
# Must include all agent save paths so recovery finds artifacts written by
# telegram_alerts, execution_state, and other multi-agent operators.
_ARTIFACT_CONFIGS = (
    ("docs/agents/bug-investigations", "notion-bug"),
    ("docs/agents/telegram-alerts", "notion-telegram"),
    ("docs/agents/execution-state", "notion-execution"),
    ("docs/agents/generated-notes", "notion-task"),
    ("docs/runbooks/triage", "notion-triage"),
)


def _is_recovery_enabled() -> bool:
    """Check AGENT_RECOVERY_ENABLED env var (default true)."""
    raw = (os.environ.get("AGENT_RECOVERY_ENABLED") or "").strip().lower()
    if raw in ("false", "0", "no"):
        return False
    return True


def _has_recovery_attempt_for_task(task_id: str, event_type: str) -> bool:
    """
    True if we have already attempted recovery of type *event_type* for this task.
    Enforces max 1 recovery attempt per task per playbook.
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return True  # Treat as "already attempted" to skip
    try:
        from app.services.agent_activity_log import get_recent_agent_events
        events = get_recent_agent_events(limit=500)
        for ev in events:
            if ev.get("event_type") == event_type and ev.get("task_id") == task_id:
                return True
        return False
    except Exception as e:
        logger.warning("agent_recovery: check prior attempt failed task_id=%s: %s", task_id, e)
        return True  # Conservative: skip if we can't check


def _parse_last_edited(ts: str | None) -> datetime | None:
    """Parse Notion last_edited_time (ISO 8601) to datetime. Returns None on parse error."""
    if not ts or not isinstance(ts, str):
        return None
    ts = ts.strip()
    if not ts:
        return None
    try:
        # Notion uses ISO 8601 e.g. "2023-03-08T18:25:00.000Z"
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _is_stale_deploying_task(task: dict[str, Any], stale_minutes: int = _DEPLOYING_STALE_MINUTES) -> bool:
    """
    True if task has been in deploying for more than stale_minutes.
    Uses last_edited_time as proxy for when status was set to deploying.
    """
    ts = _parse_last_edited(task.get("last_edited_time"))
    if ts is None:
        return False  # Can't determine staleness, skip
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    return ts <= cutoff


def _get_stale_deploying_tasks(*, max_results: int = 5, stale_minutes: int = _DEPLOYING_STALE_MINUTES) -> list[dict[str, Any]]:
    """
    Find tasks in deploying that have been stuck for > stale_minutes
    and have not yet received a recovery smoke check attempt.
    """
    try:
        from app.services.notion_task_reader import get_tasks_by_status
    except Exception as e:
        logger.warning("agent_recovery: import get_tasks_by_status failed: %s", e)
        return []

    tasks = get_tasks_by_status(["deploying", "Deploying"], max_results=max_results * 2)
    if not tasks:
        return []

    candidates: list[dict[str, Any]] = []
    for t in tasks:
        if not _is_stale_deploying_task(t, stale_minutes):
            continue
        tid = str(t.get("id") or "").strip()
        if not tid:
            continue
        if _has_recovery_attempt_for_task(tid, _RECOVERY_EVENT_TYPE):
            logger.debug("agent_recovery: task_id=%s skipped (prior orphan smoke attempt)", tid)
            continue
        candidates.append(t)
        if len(candidates) >= max_results:
            break

    return candidates


def _log_recovery_event(
    event_type: str,
    task_id: str,
    task_title: str,
    outcome: str,
    details: dict[str, Any],
) -> None:
    """Log recovery attempt to agent activity log."""
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            event_type,
            task_id=task_id,
            task_title=task_title,
            details={"outcome": outcome, **details},
        )
    except Exception as e:
        logger.debug("agent_recovery: log_agent_event failed (non-fatal): %s", e)


def run_orphan_smoke_check_playbook(
    *,
    max_tasks: int = 5,
    stale_minutes: int = _DEPLOYING_STALE_MINUTES,
) -> list[dict[str, Any]]:
    """
    Playbook: Orphan smoke check for tasks stuck in deploying.

    Detection rule:
      - Task status is "deploying"
      - Task last_edited_time > stale_minutes ago (default 10)
      - No prior recovery attempt for this task (activity log)

    Action: Run run_and_record_smoke_check once. If pass → advance to done.
    If fail → task remains non-done (blocked), existing escalation applies.

    Retry rule: Max 1 recovery attempt per task (enforced via activity log).

    Returns list of per-task result dicts.
    """
    if not _is_recovery_enabled():
        logger.debug("agent_recovery: AGENT_RECOVERY_ENABLED=false — skipping orphan smoke playbook")
        return []

    tasks = _get_stale_deploying_tasks(max_results=max_tasks, stale_minutes=stale_minutes)
    if not tasks:
        return []

    logger.info(
        "agent_recovery: orphan_smoke_playbook found %d stale deploying task(s)",
        len(tasks),
    )

    try:
        from app.services.deploy_smoke_check import run_and_record_smoke_check
    except Exception as e:
        logger.warning("agent_recovery: import run_and_record_smoke_check failed: %s", e)
        return []

    results: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        task_title = str(task.get("task") or "").strip()
        if not task_id:
            continue

        logger.info(
            "agent_recovery: running orphan smoke check task_id=%s title=%r",
            task_id,
            task_title[:50] if task_title else "",
        )

        try:
            smoke_result = run_and_record_smoke_check(
                task_id,
                advance_on_pass=True,
                current_status="deploying",
            )
            outcome = smoke_result.get("outcome", "unknown")
            advanced = smoke_result.get("advanced", False)
            blocked = smoke_result.get("blocked", False)
            summary = smoke_result.get("summary", "")

            _log_recovery_event(
                _RECOVERY_EVENT_TYPE,
                task_id,
                task_title,
                outcome,
                {
                    "advanced": advanced,
                    "blocked": blocked,
                    "summary": summary[:200],
                },
            )

            logger.info(
                "agent_recovery: orphan_smoke task_id=%s outcome=%s advanced=%s blocked=%s",
                task_id,
                outcome,
                advanced,
                blocked,
            )

            results.append({
                "task_id": task_id,
                "task_title": task_title,
                "outcome": outcome,
                "advanced": advanced,
                "blocked": blocked,
                "summary": summary,
            })
        except Exception as exc:
            logger.error(
                "agent_recovery: orphan_smoke task_id=%s raised %s",
                task_id,
                exc,
                exc_info=True,
            )
            _log_recovery_event(
                _RECOVERY_EVENT_TYPE,
                task_id,
                task_title,
                "error",
                {"error": str(exc)[:200]},
            )
            results.append({
                "task_id": task_id,
                "task_title": task_title,
                "outcome": "error",
                "advanced": False,
                "blocked": False,
                "error": str(exc),
            })

    return results


# ---------------------------------------------------------------------------
# Playbook 2: Recover stale in-progress / investigating tasks
# ---------------------------------------------------------------------------


def _is_stale_in_progress_task(
    task: dict[str, Any],
    stale_minutes: int = _IN_PROGRESS_STALE_MINUTES,
) -> bool:
    """
    True if task has been in in-progress or investigating for more than stale_minutes.
    Uses last_edited_time as proxy for when status was set.
    """
    ts = _parse_last_edited(task.get("last_edited_time"))
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    return ts <= cutoff


def _get_stale_in_progress_tasks(
    *,
    max_results: int = 5,
    stale_minutes: int = _IN_PROGRESS_STALE_MINUTES,
) -> list[dict[str, Any]]:
    """
    Find tasks in in-progress or investigating that have been stuck for > stale_minutes,
    have no investigation artifact, and have not yet received a recovery attempt.
    """
    try:
        from app.services.notion_task_reader import get_tasks_by_status
    except Exception as e:
        logger.warning("agent_recovery: import get_tasks_by_status failed: %s", e)
        return []

    tasks = get_tasks_by_status(
        ["in-progress", "In Progress", "investigating", "Investigating"],
        max_results=max_results * 3,
    )
    if not tasks:
        return []

    candidates: list[dict[str, Any]] = []
    for t in tasks:
        if not _is_stale_in_progress_task(t, stale_minutes):
            continue
        tid = str(t.get("id") or "").strip()
        if not tid:
            continue
        if _investigation_artifacts_exist(tid):
            logger.debug(
                "agent_recovery: task_id=%s skipped (investigation artifact exists)",
                tid,
            )
            continue
        if _has_recovery_attempt_for_task(tid, _RECOVERY_STALE_IN_PROGRESS_EVENT_TYPE):
            logger.debug(
                "agent_recovery: task_id=%s skipped (prior stale in-progress attempt)",
                tid,
            )
            continue
        candidates.append(t)
        if len(candidates) >= max_results:
            break

    return candidates


def run_stale_in_progress_playbook(
    *,
    max_tasks: int = 5,
    stale_minutes: int | None = None,
) -> list[dict[str, Any]]:
    """
    Playbook: Recover tasks stuck in in-progress or investigating.

    Detection rule:
      - Task status is "in-progress" or "investigating"
      - Task last_edited_time > stale_minutes ago (default 30)
      - No investigation artifact exists (agent crashed before producing one)
      - No prior recovery_stale_in_progress_attempt for this task

    Action: Reset task to planned, clear approval state, append Notion comment.
    Allows the next intake cycle to pick the task for a clean re-run.

    Retry rule: Max 1 recovery attempt per task (enforced via activity log).

    Returns list of per-task result dicts.
    """
    if stale_minutes is None:
        stale_minutes = _get_stale_in_progress_minutes()
    if not _is_recovery_enabled():
        logger.debug(
            "agent_recovery: AGENT_RECOVERY_ENABLED=false — skipping stale in-progress playbook"
        )
        return []

    tasks = _get_stale_in_progress_tasks(max_results=max_tasks, stale_minutes=stale_minutes)
    if not tasks:
        return []

    logger.info(
        "agent_recovery: stale_in_progress_playbook found %d stale task(s)",
        len(tasks),
    )

    results: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        task_title = str(task.get("task") or "").strip()
        current_status = str(task.get("status") or "").strip().lower()
        if not task_id:
            continue

        logger.info(
            "agent_recovery: running stale in-progress recovery task_id=%s title=%r status=%s",
            task_id,
            task_title[:50] if task_title else "",
            current_status,
        )

        try:
            reset_ok = _reset_task_to_planned(
                task_id,
                task_title,
                reason=(
                    f"Task was in {current_status} for >{stale_minutes} minutes with no "
                    "investigation artifact (agent may have crashed). Reset for clean re-run."
                ),
            )

            _log_recovery_event(
                _RECOVERY_STALE_IN_PROGRESS_EVENT_TYPE,
                task_id,
                task_title,
                "reset" if reset_ok else "failed",
                {
                    "reset_ok": reset_ok,
                    "previous_status": current_status,
                    "stale_minutes": stale_minutes,
                },
            )

            logger.info(
                "agent_recovery: stale_in_progress task_id=%s reset_ok=%s",
                task_id,
                reset_ok,
            )

            results.append({
                "task_id": task_id,
                "task_title": task_title,
                "outcome": "reset" if reset_ok else "failed",
                "reset_ok": reset_ok,
                "previous_status": current_status,
            })
        except Exception as exc:
            logger.error(
                "agent_recovery: stale_in_progress task_id=%s raised %s",
                task_id,
                exc,
                exc_info=True,
            )
            _log_recovery_event(
                _RECOVERY_STALE_IN_PROGRESS_EVENT_TYPE,
                task_id,
                task_title,
                "error",
                {"error": str(exc)[:200]},
            )
            results.append({
                "task_id": task_id,
                "task_title": task_title,
                "outcome": "error",
                "reset_ok": False,
                "error": str(exc),
            })

    return results


# ---------------------------------------------------------------------------
# Playbook 3: Re-validate stuck patching tasks
# ---------------------------------------------------------------------------

_INVESTIGATION_ARTIFACT_PATHS = (
    "docs/agents/bug-investigations/notion-bug-{task_id}.md",
    "docs/agents/generated-notes/notion-task-{task_id}.md",
    "docs/runbooks/triage/notion-triage-{task_id}.md",
)


def _investigation_artifacts_exist(task_id: str) -> bool:
    """
    True if required investigation artifacts exist for this task.
    Uses artifact_exists_for_task (checks all artifact configs including
    telegram-alerts, execution-state).
    """
    return artifact_exists_for_task(task_id, min_size=1)


def _is_stale_patching_task(task: dict[str, Any], stale_minutes: int = _PATCHING_STALE_MINUTES) -> bool:
    """
    True if task has been in patching for more than stale_minutes.
    Uses last_edited_time as proxy for when status was set to patching.
    """
    ts = _parse_last_edited(task.get("last_edited_time"))
    if ts is None:
        return False  # Can't determine staleness, skip
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    return ts <= cutoff


def _get_stale_patching_tasks(
    *,
    max_results: int = 5,
    stale_minutes: int = _PATCHING_STALE_MINUTES,
) -> list[dict[str, Any]]:
    """
    Find tasks in patching that have been stuck for > stale_minutes,
    have investigation artifacts, and have not yet received a recovery revalidate attempt.
    """
    try:
        from app.services.notion_task_reader import get_tasks_by_status
    except Exception as e:
        logger.warning("agent_recovery: import get_tasks_by_status failed: %s", e)
        return []

    tasks = get_tasks_by_status(["patching", "Patching"], max_results=max_results * 2)
    if not tasks:
        return []

    candidates: list[dict[str, Any]] = []
    for t in tasks:
        if not _is_stale_patching_task(t, stale_minutes):
            continue
        tid = str(t.get("id") or "").strip()
        if not tid:
            continue
        if not _investigation_artifacts_exist(tid):
            logger.debug("agent_recovery: task_id=%s skipped (investigation artifacts missing)", tid)
            continue
        if _has_recovery_attempt_for_task(tid, _RECOVERY_REVALIDATE_EVENT_TYPE):
            logger.debug("agent_recovery: task_id=%s skipped (prior revalidate attempt)", tid)
            continue
        candidates.append(t)
        if len(candidates) >= max_results:
            break

    return candidates


def run_revalidate_patching_playbook(
    *,
    max_tasks: int = 5,
    stale_minutes: int = _PATCHING_STALE_MINUTES,
) -> list[dict[str, Any]]:
    """
    Playbook: Re-validate tasks stuck in patching.

    Detection rule:
      - Task status is "patching"
      - Task last_edited_time > stale_minutes ago (default 15)
      - Required investigation artifacts exist (bug-investigation, generated-notes, or triage file)
      - No prior recovery_revalidate_patching_attempt for this task

    Action: Call advance_ready_for_patch_task once (re-runs validation).
    If validation passes → advance to release-candidate-ready.
    If validation fails → task stays in patching, existing escalation applies.

    Retry rule: Max 1 recovery attempt per task (enforced via activity log).

    Returns list of per-task result dicts.
    """
    if not _is_recovery_enabled():
        logger.debug("agent_recovery: AGENT_RECOVERY_ENABLED=false — skipping revalidate patching playbook")
        return []

    tasks = _get_stale_patching_tasks(max_results=max_tasks, stale_minutes=stale_minutes)
    if not tasks:
        return []

    logger.info(
        "agent_recovery: revalidate_patching_playbook found %d stale patching task(s)",
        len(tasks),
    )

    try:
        from app.services.agent_task_executor import advance_ready_for_patch_task
    except Exception as e:
        logger.warning("agent_recovery: import advance_ready_for_patch_task failed: %s", e)
        return []

    results: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        task_title = str(task.get("task") or "").strip()
        if not task_id:
            continue

        logger.info(
            "agent_recovery: running revalidate patching task_id=%s title=%r",
            task_id,
            task_title[:50] if task_title else "",
        )

        try:
            r = advance_ready_for_patch_task(task_id)
            ok = r.get("ok", False)
            stage = r.get("stage", "")
            final_status = r.get("final_status", "")
            summary = r.get("summary", "")

            # Map to outcome: passed if advanced to release-candidate-ready
            advanced = final_status in ("release-candidate-ready", "ready-for-deploy")
            outcome = "passed" if advanced else ("failed" if not ok else "no_advance")

            _log_recovery_event(
                _RECOVERY_REVALIDATE_EVENT_TYPE,
                task_id,
                task_title,
                outcome,
                {
                    "ok": ok,
                    "stage": stage,
                    "final_status": final_status,
                    "summary": summary[:200],
                },
            )

            logger.info(
                "agent_recovery: revalidate_patching task_id=%s outcome=%s ok=%s final_status=%s",
                task_id,
                outcome,
                ok,
                final_status,
            )

            results.append({
                "task_id": task_id,
                "task_title": task_title,
                "outcome": outcome,
                "ok": ok,
                "advanced": advanced,
                "final_status": final_status,
                "summary": summary,
            })
        except Exception as exc:
            logger.error(
                "agent_recovery: revalidate_patching task_id=%s raised %s",
                task_id,
                exc,
                exc_info=True,
            )
            _log_recovery_event(
                _RECOVERY_REVALIDATE_EVENT_TYPE,
                task_id,
                task_title,
                "error",
                {"error": str(exc)[:200]},
            )
            results.append({
                "task_id": task_id,
                "task_title": task_title,
                "outcome": "error",
                "ok": False,
                "advanced": False,
                "error": str(exc),
            })

    return results


# ---------------------------------------------------------------------------
# Playbook 3: Recover missing or empty investigation artifacts
# ---------------------------------------------------------------------------

_MIN_CONTENT_CHARS = 200  # Minimum body length for valid investigation note


def artifact_exists_for_task(task_id: str, min_size: int = 200) -> bool:
    """True if any investigation artifact exists for this task with at least min_size bytes.

    Used by executor to validate before advancing to investigation-complete.
    Checks all artifact configs (bug-investigations, telegram-alerts, execution-state, etc.).
    """
    for md_path, _ in _get_artifact_paths(task_id):
        if md_path.exists():
            try:
                if md_path.stat().st_size >= min_size:
                    return True
            except OSError:
                pass
    return False


def artifact_and_sidecar_exist_for_task(task_id: str, min_size: int = 200) -> tuple[bool, str]:
    """
    True if artifact AND sidecar both exist and artifact meets min_size.
    Returns (ok, reason) for structured logging.
    """
    for md_path, sidecar_path in _get_artifact_paths(task_id):
        if not md_path.exists():
            continue
        try:
            if md_path.stat().st_size < min_size:
                return False, f"artifact_too_small path={md_path} size={md_path.stat().st_size}"
        except OSError:
            continue
        if not sidecar_path.exists():
            return False, f"sidecar_missing path={sidecar_path}"
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
            sections = data.get("sections") if isinstance(data, dict) else None
            if not sections or not isinstance(sections, dict):
                return False, f"sidecar_empty_or_invalid path={sidecar_path}"
        except Exception as e:
            return False, f"sidecar_unreadable path={sidecar_path} err={e}"
        return True, "ok"
    return False, "artifact_missing"


def _get_artifact_paths(task_id: str) -> list[tuple[Path, Path]]:
    """Return list of (md_path, sidecar_path) for each artifact config.

    Uses get_writable_dir_for_subdir() so recovery looks in the same canonical path
    as apply/validate (repo or fallback when docs/ not writable).
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return []
    try:
        from app.services._paths import get_writable_dir_for_subdir
        out: list[tuple[Path, Path]] = []
        for subdir, prefix in _ARTIFACT_CONFIGS:
            base = get_writable_dir_for_subdir(subdir)
            md_path = base / f"{prefix}-{task_id}.md"
            sidecar_path = base / f"{prefix}-{task_id}.sections.json"
            out.append((md_path, sidecar_path))
        return out
    except Exception as e:
        logger.debug("agent_recovery: _get_artifact_paths failed task_id=%s: %s", task_id, e)
        return []


def _artifact_missing_or_empty(md_path: Path) -> bool:
    """True if the markdown artifact is missing or effectively empty."""
    if not md_path.exists():
        return True
    try:
        return md_path.stat().st_size < _MIN_CONTENT_CHARS
    except OSError:
        return True


def _extract_body_from_markdown(md_path: Path) -> str:
    """Extract the body (content after ---) from an investigation markdown file."""
    if not md_path.exists():
        return ""
    try:
        content = md_path.read_text(encoding="utf-8")
        body_start = content.find("---")
        body = content[body_start + 3:].strip() if body_start != -1 else content.strip()
        return body
    except Exception:
        return ""


def get_artifact_content_for_task(task_id: str) -> str:
    """Return the body content of the first existing investigation artifact for this task.

    Used for strict-mode proof validation before advancing to ready-for-patch.
    Returns empty string if no artifact found.
    """
    for md_path, _ in _get_artifact_paths(task_id):
        if md_path.exists():
            body = _extract_body_from_markdown(md_path)
            if len(body) >= _MIN_CONTENT_CHARS:
                return body
    return ""


def _try_regenerate_from_raw_content(md_path: Path, task_id: str, title: str) -> bool:
    """
    If the .md file has enough raw body content, parse it and rebuild.
    Returns True on success. Uses _preamble when structured sections are missing.
    """
    body = _extract_body_from_markdown(md_path)
    if len(body) < _MIN_CONTENT_CHARS:
        return False
    try:
        from app.services.openclaw_client import parse_investigation_sections
        sections = parse_investigation_sections(body)
        if not sections:
            return False
        # Allow regeneration when _preamble has content even if no ## sections
        has_content = any(
            v and str(v).strip().lower() not in ("", "n/a")
            for k, v in sections.items()
        )
        if not has_content:
            return False
        content = _rebuild_markdown_from_sections(task_id, title, sections)
        md_path.write_text(content, encoding="utf-8")
        logger.info(
            "agent_recovery: regenerated artifact from raw content task_id=%s path=%s",
            task_id,
            md_path,
        )
        return True
    except Exception as e:
        logger.debug("agent_recovery: regenerate from raw failed task_id=%s: %s", task_id, e)
        return False


def _load_sections_from_sidecar_path(sidecar_path: Path) -> dict[str, Any] | None:
    """Load sections from a .sections.json file. Returns None on failure."""
    if not sidecar_path.exists():
        return None
    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sections = data.get("sections")
        if sections and isinstance(sections, dict):
            return sections
        return None
    except Exception as e:
        logger.debug("agent_recovery: load sections failed path=%s: %s", sidecar_path, e)
        return None


def _rebuild_markdown_from_sections(
    task_id: str,
    title: str,
    sections: dict[str, Any],
) -> str:
    """Rebuild investigation markdown body from parsed sections.

    Supports both INVESTIGATION_SECTIONS (bug-investigations) and
    AGENT_OUTPUT_SECTIONS (telegram-alerts, execution-state) schemas.
    """
    try:
        from app.services.openclaw_client import (
            AGENT_OUTPUT_SECTIONS,
            INVESTIGATION_SECTIONS,
        )
    except ImportError:
        INVESTIGATION_SECTIONS = (
            "Task Summary", "Root Cause", "Risk Level", "Affected Components",
            "Affected Files", "Recommended Fix", "Testing Plan", "Notes",
        )
        AGENT_OUTPUT_SECTIONS = (
            "Issue Summary", "Scope Reviewed", "Confirmed Facts", "Mismatches",
            "Root Cause", "Proposed Minimal Fix", "Risk Level", "Validation Plan",
            "Cursor Patch Prompt",
        )

    lines: list[str] = []
    preamble = (sections.get("_preamble") or "").strip()
    if preamble:
        lines.append(preamble)
        lines.append("")

    # Use section keys present in sections; fallback to known schema order
    known_sections = set(INVESTIGATION_SECTIONS) | set(AGENT_OUTPUT_SECTIONS)
    section_order = list(AGENT_OUTPUT_SECTIONS) + [
        s for s in INVESTIGATION_SECTIONS if s not in AGENT_OUTPUT_SECTIONS
    ]
    for name in section_order:
        if name not in sections:
            continue
        val = sections.get(name)
        if val and str(val).strip().lower() not in ("", "n/a"):
            lines.append(f"## {name}\n")
            lines.append(str(val).strip())
            lines.append("")
    # Emit any extra keys not in known schemas (e.g. from future schema changes)
    for name in sorted(sections.keys()):
        if name.startswith("_") or name in known_sections:
            continue
        val = sections.get(name)
        if val and str(val).strip().lower() not in ("", "n/a"):
            lines.append(f"## {name}\n")
            lines.append(str(val).strip())
            lines.append("")

    body = "\n".join(lines).strip()
    if not body:
        body = "(Recovered from sections — content minimal)"

    return (
        f"# {title}\n\n"
        f"- **Notion page id**: `{task_id}`\n"
        f"- **Source**: OpenClaw AI analysis (recovered from sections sidecar)\n\n"
        f"---\n\n"
        f"{body}\n"
    )


def _try_regenerate_from_sections(
    md_path: Path,
    sidecar_path: Path,
    task_id: str,
    title: str,
) -> bool:
    """Regenerate markdown from sections sidecar. Returns True on success."""
    sections = _load_sections_from_sidecar_path(sidecar_path)
    if not sections:
        return False

    content = _rebuild_markdown_from_sections(task_id, title, sections)
    try:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(content, encoding="utf-8")
        logger.info(
            "agent_recovery: regenerated artifact from sections task_id=%s path=%s",
            task_id,
            md_path,
        )
        return True
    except Exception as e:
        logger.warning(
            "agent_recovery: regenerate failed task_id=%s path=%s: %s",
            task_id,
            md_path,
            e,
        )
        return False


def _reset_task_to_planned(task_id: str, task_title: str, reason: str) -> bool:
    """Reset task status to planned, clear approval state, append Notion comment."""
    task_id = (task_id or "").strip()
    if not task_id:
        return False

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    comment = (
        f"[{ts}] Recovery: Investigation artifact was missing or empty.\n"
        f"{reason}\n"
        "Task reset to planned for clean re-run. No approval gates bypassed."
    )

    try:
        from app.services.notion_tasks import TASK_STATUS_PLANNED, update_notion_task_status
        ok = update_notion_task_status(
            task_id,
            TASK_STATUS_PLANNED,
            append_comment=comment,
        )
        if not ok:
            logger.warning("agent_recovery: reset to planned failed task_id=%s", task_id)
            return False
    except Exception as e:
        logger.warning("agent_recovery: Notion reset failed task_id=%s: %s", task_id, e)
        return False

    # Clear approval state so task can be re-investigated from scratch
    try:
        from app.database import SessionLocal
        from app.models.agent_approval_state import AgentApprovalState
        if SessionLocal:
            db = SessionLocal()
            try:
                db.query(AgentApprovalState).filter_by(task_id=task_id).delete()
                db.commit()
            except Exception as e:
                logger.debug("agent_recovery: clear approval state failed: %s", e)
            finally:
                try:
                    db.close()
                except Exception:
                    pass
    except Exception as e:
        logger.debug("agent_recovery: clear approval state skipped: %s", e)

    return True


def _get_tasks_with_missing_artifacts(*, max_results: int = 5) -> list[dict[str, Any]]:
    """Find tasks in investigation-complete, ready-for-patch, or patching with missing/empty artifacts."""
    try:
        from app.services.notion_task_reader import get_tasks_by_status
    except Exception as e:
        logger.warning("agent_recovery: import get_tasks_by_status failed: %s", e)
        return []

    statuses = [
        "investigation-complete", "Investigation Complete",
        "ready-for-patch", "Ready for Patch",
        "patching", "Patching",
    ]
    tasks = get_tasks_by_status(statuses, max_results=max_results * 3)
    if not tasks:
        return []

    candidates: list[dict[str, Any]] = []
    for t in tasks:
        tid = str(t.get("id") or "").strip()
        if not tid:
            continue
        if _has_recovery_attempt_for_task(tid, _RECOVERY_MISSING_ARTIFACT_EVENT_TYPE):
            continue

        # Find the path that applies to this task (has sidecar or md file)
        applicable_path: tuple[Path, Path] | None = None
        for md_path, sidecar_path in _get_artifact_paths(tid):
            if sidecar_path.exists() or md_path.exists():
                applicable_path = (md_path, sidecar_path)
                break

        if applicable_path:
            md_path, sidecar_path = applicable_path
            if not _artifact_missing_or_empty(md_path):
                continue  # Artifact exists and is valid
        # else: no artifact files at all — task in lifecycle stage that expects one, will reset

        candidates.append(t)
        if len(candidates) >= max_results:
            break

    return candidates


def run_missing_artifact_playbook(*, max_tasks: int = 5) -> list[dict[str, Any]]:
    """
    Playbook: Recover tasks with missing or empty investigation artifacts.

    Detection rule:
      - Task status in: investigation-complete, ready-for-patch, patching
      - Expected investigation artifact (.md) is missing or empty
      - No prior recovery_missing_artifact_attempt for this task

    Recovery order:
      1. If sections sidecar exists → regenerate markdown from it
      2. Else → reset task to planned with Notion comment

    Retry rule: Max 1 recovery attempt per task.

    Returns list of per-task result dicts.
    """
    if not _is_recovery_enabled():
        logger.debug("agent_recovery: AGENT_RECOVERY_ENABLED=false — skipping missing artifact playbook")
        return []

    tasks = _get_tasks_with_missing_artifacts(max_results=max_tasks)
    if not tasks:
        return []

    logger.info(
        "agent_recovery: missing_artifact_playbook found %d task(s) with missing artifacts",
        len(tasks),
    )

    results: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        task_title = str(task.get("task") or "").strip()
        if not task_id:
            continue

        logger.info(
            "agent_recovery: running missing artifact recovery task_id=%s title=%r",
            task_id,
            task_title[:50] if task_title else "",
        )

        recovered = False
        reset_done = False
        outcome = "skipped"
        summary = ""

        try:
            title = task_title or "Untitled"

            # First pass: try to regenerate from sections sidecar
            for md_path, sidecar_path in _get_artifact_paths(task_id):
                if not _artifact_missing_or_empty(md_path):
                    continue
                if not sidecar_path.exists():
                    continue
                if _try_regenerate_from_sections(md_path, sidecar_path, task_id, title):
                    recovered = True
                    outcome = "regenerated"
                    summary = f"Regenerated {md_path.name} from sections sidecar"
                    break

            # Second pass: try to regenerate from raw content in existing .md (if any)
            if not recovered:
                for md_path, sidecar_path in _get_artifact_paths(task_id):
                    if not _artifact_missing_or_empty(md_path):
                        continue
                    if sidecar_path.exists():
                        continue  # Already tried above
                    if md_path.exists() and _try_regenerate_from_raw_content(md_path, task_id, title):
                        recovered = True
                        outcome = "regenerated"
                        summary = f"Regenerated {md_path.name} from raw content"
                        break

            # Third pass: reset to planned only when recovery truly impossible
            if not recovered:
                for md_path, sidecar_path in _get_artifact_paths(task_id):
                    if not _artifact_missing_or_empty(md_path):
                        continue
                    if sidecar_path.exists():
                        continue
                    # Log what exists before reset for debugging
                    md_exists = md_path.exists()
                    try:
                        md_size = md_path.stat().st_size if md_exists else 0
                    except OSError:
                        md_size = -1
                    logger.info(
                        "agent_recovery: missing_artifact task_id=%s md_exists=%s md_size=%d "
                        "sidecar_exists=%s — resetting to planned",
                        task_id, md_exists, md_size, sidecar_path.exists(),
                    )
                    reset_done = _reset_task_to_planned(
                        task_id,
                        task_title,
                        reason="No sections sidecar found — cannot regenerate. Task reset for clean re-investigation.",
                    )
                    outcome = "reset"
                    summary = "Task reset to planned (no sections sidecar)"
                    break

            if not recovered and not reset_done:
                outcome = "skipped"
                summary = "No missing artifacts requiring recovery"

            _log_recovery_event(
                _RECOVERY_MISSING_ARTIFACT_EVENT_TYPE,
                task_id,
                task_title,
                outcome,
                {
                    "recovered": recovered,
                    "reset_done": reset_done,
                    "summary": summary[:200],
                },
            )

            logger.info(
                "agent_recovery: missing_artifact task_id=%s outcome=%s recovered=%s reset=%s",
                task_id,
                outcome,
                recovered,
                reset_done,
            )

            results.append({
                "task_id": task_id,
                "task_title": task_title,
                "outcome": outcome,
                "recovered": recovered,
                "reset_done": reset_done,
                "summary": summary,
            })
        except Exception as exc:
            logger.error(
                "agent_recovery: missing_artifact task_id=%s raised %s",
                task_id,
                exc,
                exc_info=True,
            )
            _log_recovery_event(
                _RECOVERY_MISSING_ARTIFACT_EVENT_TYPE,
                task_id,
                task_title,
                "error",
                {"error": str(exc)[:200]},
            )
            results.append({
                "task_id": task_id,
                "task_title": task_title,
                "outcome": "error",
                "recovered": False,
                "reset_done": False,
                "error": str(exc),
            })

    return results


def run_recovery_cycle(*, max_actions: int = 5) -> list[dict[str, Any]]:
    """
    Run one recovery cycle. Invoked at the end of each scheduler cycle.

    Runs all four playbooks: orphan smoke check, stale in-progress, revalidate patching,
    missing artifact. Returns combined list of recovery actions taken (for logging).
    """
    if not _is_recovery_enabled():
        return []

    results: list[dict[str, Any]] = []
    results.extend(run_orphan_smoke_check_playbook(max_tasks=max_actions))
    results.extend(run_stale_in_progress_playbook(max_tasks=max_actions))
    results.extend(run_revalidate_patching_playbook(max_tasks=max_actions))
    results.extend(run_missing_artifact_playbook(max_tasks=max_actions))
    return results
