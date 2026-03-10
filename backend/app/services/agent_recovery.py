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
_RECOVERY_EVENT_TYPE = "recovery_orphan_smoke_attempt"
_RECOVERY_REVALIDATE_EVENT_TYPE = "recovery_revalidate_patching_attempt"
_RECOVERY_MISSING_ARTIFACT_EVENT_TYPE = "recovery_missing_artifact_attempt"

# (save_subdir, file_prefix) for OpenClaw investigation artifacts
_ARTIFACT_CONFIGS = (
    ("docs/agents/bug-investigations", "notion-bug"),
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
# Playbook 2: Re-validate stuck patching tasks
# ---------------------------------------------------------------------------

_INVESTIGATION_ARTIFACT_PATHS = (
    "docs/agents/bug-investigations/notion-bug-{task_id}.md",
    "docs/agents/generated-notes/notion-task-{task_id}.md",
    "docs/runbooks/triage/notion-triage-{task_id}.md",
)


def _investigation_artifacts_exist(task_id: str) -> bool:
    """
    True if required investigation artifacts exist for this task.
    Checks known paths for bug-investigation, generated-notes, and triage artifacts.
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return False
    try:
        from app.services._paths import workspace_root
        root = workspace_root()
        for tmpl in _INVESTIGATION_ARTIFACT_PATHS:
            path = root / tmpl.format(task_id=task_id)
            if path.is_file() and path.stat().st_size > 0:
                return True
        return False
    except Exception as e:
        logger.debug("agent_recovery: _investigation_artifacts_exist failed task_id=%s: %s", task_id, e)
        return False


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
    If validation passes → advance to awaiting-deploy-approval.
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

            # Map to outcome: passed if advanced to awaiting-deploy-approval
            advanced = final_status == "awaiting-deploy-approval"
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


def _get_artifact_paths(task_id: str) -> list[tuple[Path, Path]]:
    """Return list of (md_path, sidecar_path) for each artifact config."""
    task_id = (task_id or "").strip()
    if not task_id:
        return []
    try:
        from app.services._paths import workspace_root
        root = workspace_root()
        out: list[tuple[Path, Path]] = []
        for subdir, prefix in _ARTIFACT_CONFIGS:
            md_path = root / subdir / f"{prefix}-{task_id}.md"
            sidecar_path = root / subdir / f"{prefix}-{task_id}.sections.json"
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


def _try_regenerate_from_raw_content(md_path: Path, task_id: str, title: str) -> bool:
    """
    If the .md file has enough raw body content, parse it and rebuild.
    Returns True on success.
    """
    body = _extract_body_from_markdown(md_path)
    if len(body) < _MIN_CONTENT_CHARS:
        return False
    try:
        from app.services.openclaw_client import parse_investigation_sections
        sections = parse_investigation_sections(body)
        if not sections or all(v is None for k, v in sections.items() if k != "_preamble"):
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
    """Rebuild investigation markdown body from parsed sections."""
    try:
        from app.services.openclaw_client import INVESTIGATION_SECTIONS
    except ImportError:
        INVESTIGATION_SECTIONS = (
            "Task Summary", "Root Cause", "Risk Level", "Affected Components",
            "Affected Files", "Recommended Fix", "Testing Plan", "Notes",
        )

    lines: list[str] = []
    preamble = (sections.get("_preamble") or "").strip()
    if preamble:
        lines.append(preamble)
        lines.append("")

    for name in INVESTIGATION_SECTIONS:
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

            # Third pass: reset to planned if recovery impossible
            if not recovered:
                for md_path, sidecar_path in _get_artifact_paths(task_id):
                    if not _artifact_missing_or_empty(md_path):
                        continue
                    if sidecar_path.exists():
                        continue
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

    Runs all three playbooks: orphan smoke check, revalidate patching, missing artifact.
    Returns combined list of recovery actions taken (for logging).
    """
    if not _is_recovery_enabled():
        return []

    results: list[dict[str, Any]] = []
    results.extend(run_orphan_smoke_check_playbook(max_tasks=max_actions))
    results.extend(run_revalidate_patching_playbook(max_tasks=max_actions))
    results.extend(run_missing_artifact_playbook(max_tasks=max_actions))
    return results
