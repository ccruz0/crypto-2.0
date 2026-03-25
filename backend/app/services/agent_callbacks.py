"""
First minimal callback pack for safe agent execution.

These callbacks are intentionally low-risk:
- Documentation tasks: create/update small notes and index references under /docs
- Monitoring triage tasks: create/update incident triage notes under /docs (no runtime changes)

No shell execution, no commits, no deployment, and no trading/exchange/order lifecycle changes.
All functions return structured dicts (success/summary) and avoid raising where practical.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from app.services.agent_execution_policy import (
    ATTR_SAFE_LAB_APPLY,
    GOVERNANCE_ACTION_CLASS_KEY,
    GOV_CLASS_PATCH_PREP,
    GOV_CLASS_PROD_MUTATION,
)
from app.services import path_guard

logger = logging.getLogger(__name__)

CallbackFn = Callable[[dict[str, Any]], dict[str, Any]]


def _repo_root() -> Path:
    from app.services._paths import workspace_root
    return workspace_root()


def _note_dir_for_subdir(save_subdir: str) -> Path:
    """Return writable directory for notes; single canonical path (repo or fallback)."""
    from app.services._paths import get_writable_dir_for_subdir
    return get_writable_dir_for_subdir(save_subdir)


def _safe_task_id(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("id") or "").strip()


def _safe_task_title(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("task") or "").strip()


def _ensure_dir(p: Path) -> None:
    path_guard.safe_mkdir_lab(p, context="agent_callbacks:_ensure_dir")


def _preflight_writable_artifact_dir(artifact_dir: Path, task_id: str = "") -> tuple[bool, str]:
    """
    Verify artifact directory is writable before artifact generation.
    Returns (ok, error_msg). Use to fail fast with a clear message.
    """
    try:
        path_guard.assert_writable_lab_path(artifact_dir, context="agent_callbacks:preflight_dir")
        probe = artifact_dir / ".artifact_write_probe"
        path_guard.safe_write_text(probe, "", context="agent_callbacks:preflight_probe")
        probe.unlink(missing_ok=True)
        return True, ""
    except path_guard.PathGuardViolation as e:
        msg = f"Artifact path blocked by path guard: {artifact_dir} — {e}"
        logger.warning(
            "preflight_path_guard_blocked task_id=%s path=%s err=%s",
            task_id[:12] if task_id else "?",
            artifact_dir,
            e,
        )
        return False, msg
    except (OSError, PermissionError) as e:
        msg = f"Artifact dir not writable: {artifact_dir} — {e}"
        logger.warning("preflight_writable_check_failed task_id=%s path=%s err=%s", task_id[:12] if task_id else "?", artifact_dir, e)
        return False, msg


def _write_if_missing(path: Path, contents: str) -> bool:
    """
    Create file if missing. Return True if created, False if already existed.
    """
    if path.exists():
        return False
    path_guard.safe_write_text(path, contents, context="agent_callbacks:write_if_missing")
    return True


def _append_line_if_missing(path: Path, line: str) -> bool:
    """
    Append a single line to a file if the exact line is not already present.
    Creates the file if needed. Returns True if it appended or created, else False.
    """
    if not path.exists():
        path_guard.safe_write_text(path, line.rstrip() + "\n", encoding="utf-8", context="agent_callbacks:append_create")
        return True
    existing = path.read_text(encoding="utf-8")
    if line in existing:
        return False
    chunk = (
        ("\n" if existing and not existing.endswith("\n") else "")
        + line.rstrip()
        + "\n"
    )
    path_guard.safe_append_text(path, chunk, context="agent_callbacks:append_line")
    return True


def _markdown_links(text: str) -> list[str]:
    # Extract targets from markdown links: [label](target)
    return [m.group(1).strip() for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text or "")]


def _validate_nonempty_markdown(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing file: {path.as_posix()}"
    content = (path.read_text(encoding="utf-8") or "").strip()
    if not content:
        return False, f"empty markdown: {path.as_posix()}"
    return True, "ok"


def _validate_markdown_links_exist(md_path: Path) -> tuple[bool, str]:
    """
    Validate that any *relative* markdown link targets in md_path exist on disk.
    Skips URLs and anchors.

    Links are resolved against both the note's parent directory *and* the
    repo root because OpenClaw often generates repo-root-relative paths
    (e.g. ``docs/architecture/system-map.md``) inside notes that live
    under ``docs/agents/bug-investigations/``.
    """
    content = md_path.read_text(encoding="utf-8")
    targets = _markdown_links(content)
    root = _repo_root()
    for t in targets:
        if not t or "://" in t:
            continue
        if t.startswith("#"):
            continue
        t_clean = t.split("#", 1)[0]
        if not t_clean:
            continue
        from_parent = (md_path.parent / t_clean).resolve()
        from_root = (root / t_clean).resolve()
        if not from_parent.exists() and not from_root.exists():
            return False, f"broken relative link target: {t} (tried {from_parent.as_posix()} and {from_root.as_posix()})"
    return True, "ok"


def _is_documentation_eligible(prepared_task: dict[str, Any]) -> bool:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}

    title = str(task.get("task") or "").lower()
    project = str(task.get("project") or "").lower()
    task_type = str(task.get("type") or "").lower()
    area_name = str(repo_area.get("area_name") or "").lower()

    return any(
        k in title or k in project or k in task_type or k in area_name
        for k in ("doc", "docs", "documentation", "runbook", "readme", "agent")
    )


def _is_monitoring_triage_eligible(prepared_task: dict[str, Any]) -> bool:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}

    title = str(task.get("task") or "").lower()
    project = str(task.get("project") or "").lower()
    task_type = str(task.get("type") or "").lower()
    area_name = str(repo_area.get("area_name") or "").lower()
    matched_rules = [str(x).lower() for x in (repo_area.get("matched_rules") or [])]

    if "monitoring-infra" in matched_rules:
        return True

    return any(
        k in title or k in project or k in task_type or k in area_name
        for k in ("monitor", "monitoring", "health", "incident", "infrastructure", "ops", "nginx", "502", "504", "ssm", "ec2", "docker")
    )


def _is_bug_investigation_eligible(prepared_task: dict[str, Any]) -> bool:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    title = str(task.get("task") or "").lower()
    details = str(task.get("details") or "").lower()
    task_type = str(task.get("type") or "").lower()
    area_name = str(repo_area.get("area_name") or "").lower()
    blob = f"{title} {details} {task_type} {area_name}"

    if task_type in ("bug", "bugfix", "bug fix", "investigation", "architecture investigation"):
        return True

    keywords = (
        "not appearing",
        "not showing",
        "not working",
        "not loading",
        "not syncing",
        "broken",
        "missing data",
        "missing orders",
        "missing from",
        "disappear",
        "empty list",
        "empty page",
        "data mismatch",
        "out of sync",
        "stale data",
        "wrong data",
        "incorrect data",
        "alert spam",
        "alert rules",
    )
    return any(k in blob for k in keywords)


def _is_strategy_analysis_eligible(prepared_task: dict[str, Any]) -> bool:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    title = str(task.get("task") or "").lower()
    details = str(task.get("details") or "").lower()
    project = str(task.get("project") or "").lower()
    task_type = str(task.get("type") or "").lower()
    area_name = str(repo_area.get("area_name") or "").lower()
    matched_rules = " ".join(str(x).lower() for x in (repo_area.get("matched_rules") or []))
    blob = f"{title} {details} {project} {task_type} {area_name} {matched_rules}"
    keywords = (
        "alert logic",
        "signal quality",
        "threshold",
        "historical trend",
        "false positive",
        "false negative",
        "business logic alignment",
        "business-logic alignment",
        "volume filter",
        "indicator tuning",
        "lookback window",
        "signal",
        "strategy",
        "alerts",
    )
    return any(k in blob for k in keywords)


def _is_signal_performance_analysis_eligible(prepared_task: dict[str, Any]) -> bool:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    title = str(task.get("task") or "").lower()
    details = str(task.get("details") or "").lower()
    project = str(task.get("project") or "").lower()
    task_type = str(task.get("type") or "").lower()
    area_name = str(repo_area.get("area_name") or "").lower()
    matched_rules = " ".join(str(x).lower() for x in (repo_area.get("matched_rules") or []))
    blob = f"{title} {details} {project} {task_type} {area_name} {matched_rules}"
    keywords = (
        "signal performance",
        "signal quality",
        "historical signal review",
        "false positive",
        "false negative",
        "threshold tuning",
        "volume filter tuning",
        "lookback tuning",
        "trend confirmation tuning",
        "alert precision improvement",
    )
    return any(k in blob for k in keywords)


def _is_profile_setting_analysis_eligible(prepared_task: dict[str, Any]) -> bool:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    title = str(task.get("task") or "").lower()
    details = str(task.get("details") or "").lower()
    project = str(task.get("project") or "").lower()
    task_type = str(task.get("type") or "").lower()
    area_name = str(repo_area.get("area_name") or "").lower()
    matched_rules = " ".join(str(x).lower() for x in (repo_area.get("matched_rules") or []))
    blob = f"{title} {details} {project} {task_type} {area_name} {matched_rules}"
    keywords = (
        "per-coin settings",
        "per coin settings",
        "profile tuning",
        "conservative optimization",
        "aggressive optimization",
        "scalp optimization",
        "intraday optimization",
        "buy setting tuning",
        "sell setting tuning",
        "per-symbol parameter tuning",
        "preset optimization",
        "profile-based false positives",
        "profile-based false negatives",
        "profile-based signal quality",
        "profile setting",
        "settings profile",
    )
    return any(k in blob for k in keywords)


def apply_documentation_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    """
    Documentation-safe apply callback.

    Supported operations (minimal):
    - create a short note file under `docs/agents/generated-notes/`
    - update an index file `docs/agents/generated-notes/README.md` to reference the note
    - include a triage summary placeholder (no large invented content)
    """
    try:
        if not _is_documentation_eligible(prepared_task):
            return {"success": False, "summary": "task not eligible for documentation callback"}

        root = _repo_root()
        task = (prepared_task or {}).get("task") or {}
        repo_area = (prepared_task or {}).get("repo_area") or {}

        task_id = _safe_task_id(prepared_task)
        title = _safe_task_title(prepared_task) or "Untitled"
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        notes_dir = root / "docs" / "agents" / "generated-notes"
        _ensure_dir(notes_dir)

        note_path = notes_dir / f"notion-task-{task_id}.md"
        idx_path = notes_dir / "README.md"

        def rel_link(target_repo_path: str) -> str:
            target = (root / target_repo_path).resolve()
            try:
                return os.path.relpath(target, notes_dir.resolve())
            except Exception:
                return target_repo_path

        relevant_docs = list(repo_area.get("relevant_docs") or [])
        relevant_runbooks = list(repo_area.get("relevant_runbooks") or [])
        likely_files = list(repo_area.get("likely_files") or [])

        docs_links = "\n".join(
            f"- [{p}]({rel_link(p)})" for p in (relevant_docs[:8] or ["docs/architecture/system-map.md"])
        )
        runbook_links = "\n".join(f"- [{p}]({rel_link(p)})" for p in relevant_runbooks[:10])
        file_refs = "\n".join(f"- `{p}`" for p in likely_files[:12])

        note_contents = (
            f"# Notion task note: {title}\n\n"
            f"- **Notion page id**: `{task_id}`\n"
            f"- **Priority**: `{(task.get('priority') or '').strip()}`\n"
            f"- **Project**: `{(task.get('project') or '').strip()}`\n"
            f"- **Type**: `{(task.get('type') or '').strip()}`\n"
            f"- **Source**: `{(task.get('source') or '').strip()}`\n"
            f"- **GitHub link**: `{(task.get('github_link') or '').strip()}`\n\n"
            f"## Repo area (inferred)\n\n"
            f"- **Area**: {repo_area.get('area_name')}\n"
            f"- **Matched rules**: {', '.join(repo_area.get('matched_rules') or [])}\n\n"
            f"## Likely files/modules\n\n"
            f"{file_refs if file_refs else '- (none inferred)'}\n\n"
            f"## Relevant docs\n\n"
            f"{docs_links}\n\n"
            f"## Relevant runbooks\n\n"
            f"{runbook_links if runbook_links else '- (none)'}\n\n"
            f"## Triage summary (placeholder)\n\n"
            f"- What is the change?\n"
            f"- Which doc/runbook needs updating?\n"
            f"- What validation is required before marking deployed?\n"
        )

        created = _write_if_missing(note_path, note_contents)
        if not created:
            # Minimal safe change: append a small marker line only.
            _append_line_if_missing(note_path, "\n---\n\n- Note refreshed by agent callback (no overwrite).\n")

        idx_header = (
            "# Generated task notes (agent)\n\n"
            "This directory contains small, safe notes generated by agent callbacks.\n"
            "They are meant for triage and documentation updates only.\n\n"
        )
        _write_if_missing(idx_path, idx_header)

        idx_line = f"- [Notion task {task_id}: {title}](notion-task-{task_id}.md)"
        _append_line_if_missing(idx_path, idx_line)

        return {"success": True, "summary": f"documentation note prepared at docs/agents/generated-notes/notion-task-{task_id}.md"}
    except Exception as e:
        logger.exception("apply_documentation_task failed: %s", e)
        return {"success": False, "summary": str(e)}


def validate_documentation_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    """
    Documentation validation callback.

    Confirms:
    - generated note exists
    - markdown is non-empty
    - relative markdown links referenced in the note resolve to existing files
    """
    try:
        task_id = _safe_task_id(prepared_task)
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        root = _repo_root()
        note_path = root / "docs" / "agents" / "generated-notes" / f"notion-task-{task_id}.md"

        ok, msg = _validate_nonempty_markdown(note_path)
        if not ok:
            return {"success": False, "summary": msg}

        ok2, msg2 = _validate_markdown_links_exist(note_path)
        if not ok2:
            return {"success": False, "summary": msg2}

        return {"success": True, "summary": "documentation note validated (non-empty, links OK)"}
    except Exception as e:
        logger.exception("validate_documentation_task failed: %s", e)
        return {"success": False, "summary": str(e)}


def apply_monitoring_triage_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    """
    Monitoring/ops triage apply callback (no runtime changes).

    Supported operations (minimal):
    - create/update a triage note under `docs/runbooks/triage/`
    - include incident summary placeholder + inferred modules/docs/runbooks
    """
    try:
        if not _is_monitoring_triage_eligible(prepared_task):
            return {"success": False, "summary": "task not eligible for monitoring triage callback"}

        root = _repo_root()
        task = (prepared_task or {}).get("task") or {}
        repo_area = (prepared_task or {}).get("repo_area") or {}

        task_id = _safe_task_id(prepared_task)
        title = _safe_task_title(prepared_task) or "Untitled"
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        triage_dir = root / "docs" / "runbooks" / "triage"
        _ensure_dir(triage_dir)

        note_path = triage_dir / f"notion-triage-{task_id}.md"
        idx_path = triage_dir / "README.md"

        def rel_link(from_dir: Path, target_repo_path: str) -> str:
            target = (root / target_repo_path).resolve()
            try:
                return os.path.relpath(target, from_dir.resolve())
            except Exception:
                return target_repo_path

        likely_files = list(repo_area.get("likely_files") or [])
        relevant_docs = list(repo_area.get("relevant_docs") or [])
        relevant_runbooks = list(repo_area.get("relevant_runbooks") or [])

        modules_block = "\n".join(f"- `{p}`" for p in likely_files[:12]) or "- (none inferred)"
        docs_block = "\n".join(f"- [{p}]({rel_link(triage_dir, p)})" for p in relevant_docs[:10]) or "- (none inferred)"
        runbooks_block = "\n".join(f"- [{p}]({rel_link(triage_dir, p)})" for p in relevant_runbooks[:12]) or "- (none inferred)"

        note_contents = (
            f"# Notion monitoring triage: {title}\n\n"
            f"- **Notion page id**: `{task_id}`\n"
            f"- **Priority**: `{(task.get('priority') or '').strip()}`\n"
            f"- **Project**: `{(task.get('project') or '').strip()}`\n"
            f"- **Type**: `{(task.get('type') or '').strip()}`\n"
            f"- **GitHub link**: `{(task.get('github_link') or '').strip()}`\n\n"
            f"## Affected modules (inferred)\n\n"
            f"{modules_block}\n\n"
            f"## Relevant docs\n\n"
            f"{docs_block}\n\n"
            f"## Relevant runbooks\n\n"
            f"{runbooks_block}\n\n"
            f"## Incident summary (placeholder)\n\n"
            f"- Symptoms:\n"
            f"- When did it start:\n"
            f"- Impact:\n"
            f"- Observed errors/logs:\n\n"
            f"## Next steps (short)\n\n"
            f"- Confirm current system health (`/api/health`) and check logs.\n"
            f"- Follow the most relevant runbook above.\n"
            f"- Identify the smallest safe fix; do not change trading/order lifecycle in triage.\n"
        )

        created = _write_if_missing(note_path, note_contents)
        if not created:
            _append_line_if_missing(note_path, "\n---\n\n- Triage note touched by agent callback (no overwrite).\n")

        idx_header = (
            "# Triage notes (agent)\n\n"
            "Small incident/monitoring triage notes generated by agent callbacks.\n"
            "These are documentation-only and must not change runtime behavior.\n\n"
        )
        _write_if_missing(idx_path, idx_header)
        idx_line = f"- [Notion triage {task_id}: {title}](notion-triage-{task_id}.md)"
        _append_line_if_missing(idx_path, idx_line)

        # Notion → Cursor: create handoff file and write instruction on the Notion task so the task "tells" Cursor what to do
        triage_note = f"docs/runbooks/triage/notion-triage-{task_id}.md"
        cursor_instruction = (
            f"Cursor: Para ejecutar los cambios, abre Cursor en el repo y di: \"Ejecuta los pasos del triage\" o \"pick the triage and run the changes\". "
            f"Archivo: {triage_note} (sección \"Cursor: run these steps\"). "
            "O usa el Cursor Bridge: POST /api/agent/cursor-bridge/run con task_id."
        )
        try:
            from app.services.cursor_handoff import save_cursor_handoff
            handoff_prompt = (
                f"# Tarea: {title}\n\n"
                f"Notion task id: `{task_id}`\n\n"
                "**Instrucción:** Ejecuta los pasos del triage para esta tarea.\n\n"
                f"1. Lee el archivo **{triage_note}** en este repo.\n"
                "2. Sigue la sección **\"Cursor: run these steps (actionable fix)\"** en orden (diagnóstico, aplicar fixes del runbook, reiniciar backend si aplica, re-ejecutar diagnóstico).\n"
                "3. No cambies lógica de trading/órdenes; solo config de Telegram, env y pasos del runbook.\n"
            )
            save_cursor_handoff(task_id, handoff_prompt, title=title)
        except Exception as handoff_err:
            logger.debug("cursor handoff for triage task_id=%s skipped: %s", task_id, handoff_err)

        try:
            from app.services.notion_tasks import update_notion_task_metadata
            # Set OpenClaw Report URL to triage path so Cursor/humans can open it; append_comment adds the instruction to the page
            update_notion_task_metadata(
                task_id,
                {"openclaw_report_url": triage_note},
                append_comment=cursor_instruction,
            )
        except Exception as meta_err:
            logger.debug("Notion metadata/comment for Cursor instruction skipped task_id=%s: %s", task_id, meta_err)

        return {"success": True, "summary": f"monitoring triage note prepared at docs/runbooks/triage/notion-triage-{task_id}.md"}
    except Exception as e:
        logger.exception("apply_monitoring_triage_task failed: %s", e)
        return {"success": False, "summary": str(e)}


def validate_monitoring_triage_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    """
    Monitoring triage validation callback.

    Confirms:
    - triage note exists and is non-empty
    - it includes the sections: Affected modules, Relevant docs, Next steps
    - it includes at least one inferred module or doc link (not just empty placeholders)
    """
    try:
        task_id = _safe_task_id(prepared_task)
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        root = _repo_root()
        note_path = root / "docs" / "runbooks" / "triage" / f"notion-triage-{task_id}.md"
        ok, msg = _validate_nonempty_markdown(note_path)
        if not ok:
            return {"success": False, "summary": msg}

        content = note_path.read_text(encoding="utf-8")
        required_markers = ["## Affected modules", "## Relevant docs", "## Next steps"]
        for m in required_markers:
            if m not in content:
                return {"success": False, "summary": f"missing required section: {m}"}

        # Ensure some concrete content exists (a backticked file path or a markdown link).
        has_module_ref = "`backend/" in content or "`docker-compose.yml`" in content
        has_doc_link = bool(_markdown_links(content))
        if not (has_module_ref or has_doc_link):
            return {"success": False, "summary": "triage note missing concrete module/doc references"}

        # Validate relative links if any
        ok2, msg2 = _validate_markdown_links_exist(note_path)
        if not ok2:
            return {"success": False, "summary": msg2}

        return {"success": True, "summary": "monitoring triage note validated (sections present, links OK)"}
    except Exception as e:
        logger.exception("validate_monitoring_triage_task failed: %s", e)
        return {"success": False, "summary": str(e)}


def apply_bug_investigation_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    """
    Bug investigation apply callback (documentation-only, no runtime changes).

    Creates a structured investigation note under `docs/agents/bug-investigations/`
    with the task metadata, inferred area, affected modules, relevant docs/runbooks,
    and a placeholder checklist for the human investigator.
    """
    try:
        if not _is_bug_investigation_eligible(prepared_task):
            return {"success": False, "summary": "task not eligible for bug investigation callback"}

        root = _repo_root()
        task = (prepared_task or {}).get("task") or {}
        repo_area = (prepared_task or {}).get("repo_area") or {}

        task_id = _safe_task_id(prepared_task)
        title = _safe_task_title(prepared_task) or "Untitled"
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        inv_dir = _note_dir_for_subdir("docs/agents/bug-investigations")
        _ensure_dir(inv_dir)
        ok, err = _preflight_writable_artifact_dir(inv_dir, task_id)
        if not ok:
            return {"success": False, "summary": err}

        note_path = inv_dir / f"notion-bug-{task_id}.md"
        logger.info("artifact_write_started task_id=%s path=%s", task_id[:12] if task_id else "?", note_path)

        def rel_link(from_dir: Path, target_repo_path: str) -> str:
            target = (root / target_repo_path).resolve()
            try:
                return os.path.relpath(target, from_dir.resolve())
            except Exception:
                return target_repo_path

        likely_files = list(repo_area.get("likely_files") or [])
        relevant_docs = list(repo_area.get("relevant_docs") or [])
        relevant_runbooks = list(repo_area.get("relevant_runbooks") or [])
        area_name = repo_area.get("area_name") or "Unknown"
        matched_rules = repo_area.get("matched_rules") or []

        modules_block = "\n".join(f"- `{p}`" for p in likely_files[:12]) or "- (none inferred)"
        docs_block = "\n".join(
            f"- [{p}]({rel_link(inv_dir, p)})" for p in relevant_docs[:10]
        ) or "- (none inferred)"
        runbooks_block = "\n".join(
            f"- [{p}]({rel_link(inv_dir, p)})" for p in relevant_runbooks[:12]
        ) or "- (none inferred)"

        note_contents = (
            f"# Bug investigation: {title}\n\n"
            f"- **Notion page id**: `{task_id}`\n"
            f"- **Priority**: `{(task.get('priority') or '').strip()}`\n"
            f"- **Project**: `{(task.get('project') or '').strip()}`\n"
            f"- **Type**: `{(task.get('type') or '').strip()}`\n"
            f"- **GitHub link**: `{(task.get('github_link') or '').strip()}`\n\n"
            f"## Inferred area\n\n"
            f"- **Area**: {area_name}\n"
            f"- **Matched rules**: {', '.join(matched_rules)}\n\n"
            f"## Affected modules\n\n"
            f"{modules_block}\n\n"
            f"## Relevant docs\n\n"
            f"{docs_block}\n\n"
            f"## Relevant runbooks\n\n"
            f"{runbooks_block}\n\n"
            f"## Bug details\n\n"
            f"- **Reported symptom**: {(task.get('details') or title).strip()}\n"
            f"- **Reproducible**: (to be confirmed)\n"
            f"- **Severity**: (inferred from priority: {(task.get('priority') or 'unknown').strip()})\n\n"
            f"## Investigation checklist\n\n"
            f"- [ ] Confirm current behavior (logs, health endpoint, dashboard)\n"
            f"- [ ] Identify root cause in affected module(s)\n"
            f"- [ ] Determine smallest safe fix\n"
            f"- [ ] Verify fix does not affect unrelated areas\n"
            f"- [ ] Update relevant docs/runbooks if behavior changes\n"
            f"- [ ] Validate (tests/lint/manual) before marking deployed\n"
        )

        try:
            created = _write_if_missing(note_path, note_contents)
            if not created:
                _append_line_if_missing(
                    note_path,
                    "\n---\n\n- Investigation note touched by agent callback (no overwrite).\n",
                )
            logger.info("artifact_write_succeeded task_id=%s path=%s chars=%d", task_id[:12] if task_id else "?", note_path, len(note_contents))
        except Exception as e:
            logger.warning("artifact_write_failed task_id=%s path=%s err=%s", task_id[:12] if task_id else "?", note_path, e)
            return {"success": False, "summary": f"Failed to write artifact: {e}"}

        # No README index write: avoids Permission denied on repo-owned README.md in Docker.
        # Artifacts are per-task (.md + .sections.json); index is optional and not required.

        # Parse ALL ## sections from the note so .sections.json is complete at creation time.
        # This ensures deploy approval can read only from .sections.json (single source of truth).
        try:
            from app.services.openclaw_client import parse_all_markdown_sections
            sidecar_sections = parse_all_markdown_sections(note_contents)
        except Exception as e:
            logger.warning("parse_all_markdown_sections failed task_id=%s: %s — using _preamble", task_id, e)
            sidecar_sections = {}
        if not sidecar_sections:
            sidecar_sections = {"_preamble": note_contents}

        _REQUIRED_DEPLOY = ("Task Summary", "Root Cause", "Recommended Fix", "Affected Files")
        sections_complete = all(
            sidecar_sections.get(k) and str(sidecar_sections.get(k)).strip().lower() not in ("", "n/a")
            for k in _REQUIRED_DEPLOY
        )
        sidecar_path = inv_dir / f"notion-bug-{task_id}.sections.json"
        sidecar_data = {
            "task_id": task_id,
            "title": title,
            "source": "fallback",
            "sections": sidecar_sections,
            "sections_complete": sections_complete,
        }
        try:
            path_guard.safe_write_text(
                sidecar_path,
                json.dumps(sidecar_data, indent=2, ensure_ascii=False) + "\n",
                context="agent_callbacks:bug_sidecar",
            )
            logger.info("sidecar_write_succeeded task_id=%s path=%s", task_id[:12] if task_id else "?", sidecar_path)
        except Exception as e:
            logger.warning("Failed to write bug investigation sidecar task_id=%s: %s", task_id, e)

        summary_path = (inv_dir / f"notion-bug-{task_id}.md").as_posix()
        return {
            "success": True,
            "summary": f"bug investigation note prepared at {summary_path}",
        }
    except Exception as e:
        logger.exception("apply_bug_investigation_task failed: %s", e)
        return {"success": False, "summary": str(e)}


def validate_bug_investigation_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    """
    Bug investigation validation callback.

    Confirms:
    - investigation note exists and is non-empty
    - required sections (Affected modules, Relevant docs, Investigation checklist) are present
    - at least one concrete module reference or doc link exists
    """
    try:
        task_id = _safe_task_id(prepared_task)
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        inv_dir = _note_dir_for_subdir("docs/agents/bug-investigations")
        note_path = inv_dir / f"notion-bug-{task_id}.md"

        ok, msg = _validate_nonempty_markdown(note_path)
        if not ok:
            return {"success": False, "summary": msg}

        content = note_path.read_text(encoding="utf-8")
        required_markers = [
            "## Affected modules",
            "## Relevant docs",
            "## Investigation checklist",
        ]
        for m in required_markers:
            if m not in content:
                return {"success": False, "summary": f"missing required section: {m}"}

        has_module_ref = "`backend/" in content or "`docker-compose" in content
        has_doc_link = bool(_markdown_links(content))
        if not (has_module_ref or has_doc_link):
            return {"success": False, "summary": "investigation note missing concrete module/doc references"}

        ok2, msg2 = _validate_markdown_links_exist(note_path)
        if not ok2:
            return {"success": False, "summary": msg2}

        return {"success": True, "summary": "bug investigation note validated (sections present, refs OK)"}
    except Exception as e:
        logger.exception("validate_bug_investigation_task failed: %s", e)
        return {"success": False, "summary": str(e)}


_OPENCLAW_FALLBACK_MARKERS = (
    "no response from openclaw",
    "openclaw not configured",
    "template fallback",
    "openclaw error",
    "openclaw returned empty",
    "connection failed",
    "timeout after",
    "insufficient credit",
    "rate limit",
    "payment required",
    "quota exceeded",
)

# Retryable errors: do NOT use template fallback — task stays in-progress for retry
_RETRYABLE_LLM_ERROR_MARKERS = (
    "timeout",
    "429",
    "too many requests",
    "502",
    "503",
    "504",
    "connection reset",
    "connection refused",
    "temporary upstream failure",
    "upstream failure",
)

# Generic investigation output: lacks actionable root cause
_GENERIC_INVESTIGATION_MARKERS = (
    "further investigation needed",
    "further investigation required",
    "unable to determine",
    "could not determine",
    "unclear at this time",
    "requires manual investigation",
    "check the logs",
    "review the logs",
    "see logs for",
    "consult the documentation",
    "insufficient information",
    "more information needed",
    "additional information required",
)

_MIN_INVESTIGATION_CONTENT_CHARS = 200
# Agent output: require all 9 sections and longer body
_MIN_AGENT_BODY_CHARS = 500
_AGENT_CRITICAL_SECTIONS = ("Root Cause", "Proposed Minimal Fix", "Risk Level", "Cursor Patch Prompt")
_AGENT_CRITICAL_MIN_CHARS = 15  # Excluding "N/A"

_OPENCLAW_MAX_RETRIES = 1
_OPENCLAW_RETRY_DELAY_S = 5
_OPENCLAW_FAILURE_PREVIEW_CHARS = 800

# Cost-control switch for automatic OpenClaw execution.
# Defaults:
# - AWS runtime: disabled (safe)
# - non-AWS runtime: enabled
ENV_OPENCLAW_AUTO_EXECUTION_ENABLED = "ATP_OPENCLAW_AUTO_EXECUTION_ENABLED"
ENV_OPENCLAW_ALLOWED_TASK_IDS = "ATP_OPENCLAW_ALLOWED_TASK_IDS"


def _openclaw_auto_execution_enabled() -> bool:
    raw = (os.environ.get(ENV_OPENCLAW_AUTO_EXECUTION_ENABLED) or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    try:
        from app.core.runtime import is_aws_runtime
        return not bool(is_aws_runtime())
    except Exception:
        return True


def _openclaw_allowed_task_ids() -> set[str]:
    raw = (os.environ.get(ENV_OPENCLAW_ALLOWED_TASK_IDS) or "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _task_allows_openclaw(prepared_task: dict[str, Any]) -> bool:
    task = (prepared_task or {}).get("task") or {}
    raw = task.get("allow_openclaw")
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "approved", "allow", "allowed")


def _verification_fail_max_attempts() -> int:
    raw = (os.environ.get("ATP_VERIFICATION_FAIL_MAX_ATTEMPTS") or "").strip()
    try:
        n = int(raw) if raw else 3
    except (TypeError, ValueError):
        n = 3
    return max(1, min(n, 20))


def _task_token_budget_limit() -> int:
    raw = (os.environ.get("ATP_TASK_TOKEN_BUDGET") or "").strip()
    try:
        n = int(raw) if raw else 0
    except (TypeError, ValueError):
        n = 0
    return max(0, min(n, 10_000_000))


def _is_transient_openclaw_error(msg: str) -> bool:
    m = (msg or "").lower()
    transient_markers = (
        "timeout",
        "429",
        "http 429",
        "502",
        "http 502",
        "503",
        "http 503",
        "504",
        "http 504",
        "connection reset",
        "connection refused",
        "temporary upstream failure",
        "upstream failure",
    )
    return any(x in m for x in transient_markers)


def _verification_verdict_cache_path(task_id: str) -> Path:
    root = _repo_root()
    cache_dir = root / "docs" / "agents" / "verification-feedback"
    path_guard.safe_mkdir_lab(cache_dir, context="agent_callbacks:verification_feedback_dir")
    return cache_dir / f"{task_id}.verdict.json"


def _call_openclaw_once(
    send_to_openclaw: Callable,
    user_prompt: str,
    instructions: str,
    task_id: str,
    model_chain_override: list[str] | None = None,
    *,
    sections: Optional[tuple[str, ...]] = None,
) -> tuple[dict[str, Any] | None, str]:
    """Single OpenClaw call + quality gate.  Returns (result_or_None, error_reason)."""
    try:
        kwargs: dict[str, Any] = {"task_id": task_id, "instructions": instructions}
        if model_chain_override is not None:
            kwargs["model_chain_override"] = model_chain_override
        result = send_to_openclaw(user_prompt, **kwargs)
    except Exception as e:
        return None, f"OpenClaw error: {e}"

    if not result.get("success"):
        return None, f"OpenClaw error: {result.get('error', 'unknown')}"

    content = result.get("content") or ""
    if not content.strip():
        return None, "OpenClaw returned empty response"

    content_lower = content.lower()
    for marker in _OPENCLAW_FALLBACK_MARKERS:
        if marker in content_lower:
            return None, f"OpenClaw returned fallback/error content: '{marker}'"

    from app.services.openclaw_client import INVESTIGATION_SECTIONS
    use_sections = sections if sections is not None else INVESTIGATION_SECTIONS
    found_sections = [s for s in use_sections if f"## {s}" in content]
    if not found_sections and len(content.strip()) < _MIN_INVESTIGATION_CONTENT_CHARS:
        preview = content.strip()[:_OPENCLAW_FAILURE_PREVIEW_CHARS].replace("\n", "\\n")
        logger.warning(
            "openclaw_validation_failed_raw task_id=%s response_len=%d preview=%r",
            task_id,
            len(content.strip()),
            preview,
        )
        return None, (
            f"OpenClaw response lacks structured sections and is too short "
            f"({len(content.strip())} chars)"
        )

    return result, ""


def _apply_via_openclaw(
    prepared_task: dict[str, Any],
    prompt_builder_fn: Callable,
    save_subdir: str,
    file_prefix: str,
    fallback_fn: Optional[CallbackFn] = None,
    *,
    use_agent_schema: bool = False,
) -> dict[str, Any]:
    """Send a task to OpenClaw for AI analysis, save the result, fall back to template on failure."""
    task_id = _safe_task_id(prepared_task)
    title = _safe_task_title(prepared_task) or "Untitled"

    if not _openclaw_auto_execution_enabled():
        allowed_task_ids = _openclaw_allowed_task_ids()
        if _task_allows_openclaw(prepared_task):
            logger.info(
                "openclaw_cost_control_notion_approved task_id=%s field=Allow OpenClaw -- allowing execution while global auto-execution is disabled",
                task_id,
            )
        elif task_id and task_id in allowed_task_ids:
            logger.info(
                "openclaw_cost_control_allowlisted task_id=%s env=%s -- allowing execution while global auto-execution is disabled",
                task_id,
                ENV_OPENCLAW_ALLOWED_TASK_IDS,
            )
        else:
            logger.info(
                "openclaw_cost_control_skip task_id=%s title=%r env=%s -- automatic OpenClaw execution disabled",
                task_id,
                title[:120],
                ENV_OPENCLAW_AUTO_EXECUTION_ENABLED,
            )
            return {
                "success": False,
                "summary": (
                    "OpenClaw auto-execution disabled by cost-control "
                    f"({ENV_OPENCLAW_AUTO_EXECUTION_ENABLED})"
                ),
                "retryable": False,
            }

    try:
        from app.services.openclaw_client import is_openclaw_configured, send_to_openclaw
    except Exception as e:
        logger.warning(
            "openclaw_fallback reason=import_failed error=%s task_id=%s use_agent_schema=%s",
            e, task_id, use_agent_schema,
        )
        if fallback_fn:
            logger.info("openclaw_fallback using template fallback task_id=%s", task_id)
            return fallback_fn(prepared_task)
        return {"success": False, "summary": f"openclaw_client unavailable: {e}"}

    if not is_openclaw_configured():
        logger.warning(
            "openclaw_fallback reason=not_configured task_id=%s use_agent_schema=%s",
            task_id, use_agent_schema,
        )
        if fallback_fn:
            logger.info("openclaw_fallback using template fallback task_id=%s", task_id)
            return fallback_fn(prepared_task)
        return {"success": False, "summary": "OPENCLAW_API_TOKEN not configured"}

    # Debug: trace execution_mode before prompt build
    _exec_from_pt = (prepared_task or {}).get("execution_mode")
    _exec_from_task = ((prepared_task or {}).get("task") or {}).get("execution_mode")
    _exec_mode = _exec_from_pt or _exec_from_task or "?"
    logger.info(
        "execution_mode_trace _apply_via_openclaw task_id=%s execution_mode=%s (from_pt=%s from_task=%s)",
        task_id, _exec_mode, _exec_from_pt, _exec_from_task,
    )
    if _exec_mode == "strict":
        logger.info("STRICT MODE ACTIVE at _apply_via_openclaw task_id=%s", task_id)

    try:
        user_prompt, instructions = prompt_builder_fn(prepared_task)
    except Exception as e:
        logger.warning("OpenClaw prompt build failed for task %s: %s", task_id, e)
        if fallback_fn:
            return fallback_fn(prepared_task)
        return {"success": False, "summary": f"prompt build error: {e}"}

    # Strict mode: prepend hard override block when execution_mode=strict
    try:
        from app.services.openclaw_client import prepend_strict_mode_if_needed
        user_prompt = prepend_strict_mode_if_needed(user_prompt, prepared_task)
    except Exception as e:
        logger.debug("prepend_strict_mode_if_needed failed: %s — continuing without strict block", e)

    # Append verification feedback if this is a re-investigation after failed verification
    root = _repo_root()
    feedback_path = root / "docs" / "agents" / "verification-feedback" / f"{task_id}.txt"
    if feedback_path.exists():
        try:
            prev_feedback = feedback_path.read_text(encoding="utf-8").strip()
            if prev_feedback:
                prev_feedback = prev_feedback[:400]
                user_prompt += (
                    f"\n\n---\n\n"
                    f"**Previous attempt failed solution verification.**\n"
                    f"Feedback: {prev_feedback}\n\n"
                    f"Please improve your analysis to address this feedback."
                )
                logger.info("OpenClaw apply: including verification feedback for task %s", task_id)
        except Exception as e:
            logger.warning("Could not read verification feedback for task %s: %s", task_id, e)
        try:
            feedback_path.unlink()
        except Exception:
            pass

    # Task-type routing: use cheap chain for doc/monitoring when configured
    try:
        from app.services.openclaw_client import get_apply_model_chain_override
        chain_override = get_apply_model_chain_override(prepared_task, save_subdir)
    except Exception as e:
        logger.debug("get_apply_model_chain_override failed: %s — using main chain", e)
        chain_override = None
    if chain_override:
        logger.info("OpenClaw apply: using cheap chain for task %s save_subdir=%s", task_id, save_subdir)

    last_error = ""
    result: dict[str, Any] | None = None
    max_attempts = 1 + _OPENCLAW_MAX_RETRIES
    token_budget = _task_token_budget_limit()
    token_spent = 0

    call_sections: Optional[tuple[str, ...]] = None
    if use_agent_schema:
        try:
            from app.services.openclaw_client import AGENT_OUTPUT_SECTIONS
            call_sections = AGENT_OUTPUT_SECTIONS
        except ImportError as e:
            logger.error(
                "AGENT_OUTPUT_SECTIONS import failed (deterministic) task_id=%s: %s — using fallback",
                task_id, e,
            )
            if fallback_fn:
                logger.info("openclaw_fallback reason=agent_schema_unavailable task_id=%s", task_id)
                return fallback_fn(prepared_task)
            return {"success": False, "summary": f"agent schema unavailable: {e}"}

    for attempt in range(1, max_attempts + 1):
        result, last_error = _call_openclaw_once(
            send_to_openclaw, user_prompt, instructions, task_id,
            model_chain_override=chain_override,
            sections=call_sections,
        )
        if result is not None:
            usage = result.get("usage") if isinstance(result, dict) else None
            if isinstance(usage, dict):
                try:
                    token_spent += int(usage.get("total_tokens") or 0)
                except (TypeError, ValueError):
                    pass
            if token_budget > 0 and token_spent >= token_budget:
                last_error = f"token budget exhausted ({token_spent}/{token_budget})"
                logger.warning(
                    "OpenClaw attempt %d/%d blocked for task %s: %s",
                    attempt, max_attempts, task_id, last_error,
                )
                result = None
            break
        if token_budget > 0 and token_spent >= token_budget:
            last_error = f"token budget exhausted ({token_spent}/{token_budget})"
            logger.warning(
                "OpenClaw attempt %d/%d blocked for task %s: %s",
                attempt, max_attempts, task_id, last_error,
            )
            break
        if attempt < max_attempts and _is_transient_openclaw_error(last_error):
            logger.warning(
                "OpenClaw attempt %d/%d failed for task %s: %s — retrying in %ds",
                attempt, max_attempts, task_id, last_error, _OPENCLAW_RETRY_DELAY_S,
            )
            time.sleep(_OPENCLAW_RETRY_DELAY_S)
        else:
            if attempt < max_attempts:
                logger.warning(
                    "OpenClaw attempt %d/%d failed for task %s: %s — non-transient, no retry",
                    attempt, max_attempts, task_id, last_error,
                )
            else:
                logger.warning(
                    "OpenClaw attempt %d/%d failed for task %s: %s — no retries left",
                    attempt, max_attempts, task_id, last_error,
                )
            break

    if result is None:
        logger.warning(
            "openclaw_fallback reason=openclaw_error error=%s task_id=%s use_agent_schema=%s",
            last_error, task_id, use_agent_schema,
        )
        # Retryable errors (rate limit, timeout, etc.): do NOT use fallback — task stays in-progress for retry
        last_err_lower = (last_error or "").lower()
        is_retryable = any(m in last_err_lower for m in _RETRYABLE_LLM_ERROR_MARKERS)
        if is_retryable:
            logger.info(
                "openclaw_fallback retryable_error task_id=%s — NOT using fallback, task will retry next cycle",
                task_id,
            )
            return {"success": False, "summary": last_error, "retryable": True}
        if fallback_fn:
            logger.info("openclaw_fallback using template fallback task_id=%s", task_id)
            return fallback_fn(prepared_task)
        return {"success": False, "summary": last_error}

    content = result.get("content") or ""

    # Bug-investigation path: OpenClaw sometimes returns plain prose/apology text
    # without any "## ..." sections. In that case, use the deterministic bug
    # template fallback so validation has a structured artifact to evaluate.
    if (not use_agent_schema) and file_prefix == "notion-bug" and fallback_fn is not None:
        try:
            from app.services.openclaw_client import INVESTIGATION_SECTIONS
            inv_sections = INVESTIGATION_SECTIONS
        except ImportError:
            inv_sections = (
                "Task Summary", "Root Cause", "Risk Level", "Affected Components",
                "Affected Files", "Recommended Fix", "Testing Plan", "Notes",
            )
        structured_found = [s for s in inv_sections if f"## {s}" in content]
        if not structured_found:
            logger.warning(
                "openclaw_apply_unstructured_output task_id=%s save_subdir=%s -- using fallback template",
                task_id, save_subdir,
            )
            return fallback_fn(prepared_task)

    # Parse structured sections (gracefully returns None values for missing ones)
    try:
        from app.services.openclaw_client import (
            parse_agent_output_sections,
            parse_investigation_sections,
        )
        if use_agent_schema:
            sections = parse_agent_output_sections(content)
        else:
            sections = parse_investigation_sections(content)
    except Exception:
        sections = {}

    # Stash sections on prepared_task for downstream metadata enrichment
    if sections:
        prepared_task["_openclaw_sections"] = sections

    out_dir = _note_dir_for_subdir(save_subdir)
    _ensure_dir(out_dir)
    ok, err = _preflight_writable_artifact_dir(out_dir, task_id)
    if not ok:
        return {"success": False, "summary": err}

    note_path = out_dir / f"{file_prefix}-{task_id}.md"
    logger.info("artifact_write_started task_id=%s path=%s", task_id[:12] if task_id else "?", note_path)
    note_contents = (
        f"# {title}\n\n"
        f"- **Notion page id**: `{task_id}`\n"
        f"- **Source**: OpenClaw AI analysis\n\n"
        f"---\n\n"
        f"{content}\n"
    )

    try:
        path_guard.safe_write_text(note_path, note_contents, context="agent_callbacks:openclaw_note_md")
        logger.info("artifact_write_succeeded task_id=%s path=%s chars=%d", task_id[:12] if task_id else "?", note_path, len(note_contents))
    except Exception as e:
        logger.warning("artifact_write_failed task_id=%s path=%s err=%s", task_id[:12] if task_id else "?", note_path, e)
        return {"success": False, "summary": f"Failed to write artifact: {e}"}

    # Parse ALL ## sections from the canonical artifact so .sections.json is always complete.
    # This is the single source of truth; deploy approval reads only from .sections.json.
    try:
        from app.services.openclaw_client import parse_all_markdown_sections
        full_sections = parse_all_markdown_sections(note_contents)
    except Exception as e:
        logger.warning("parse_all_markdown_sections failed task_id=%s: %s — using schema parse", task_id, e)
        full_sections = {}
    if full_sections:
        sidecar_sections = full_sections
    elif sections:
        # Fallback: schema-specific parse (may have None values)
        sidecar_sections = {k: (v or "") for k, v in sections.items() if v is not None}
        if not sidecar_sections:
            sidecar_sections = {"_preamble": content.strip()[:5000] if content else ""}
    else:
        sidecar_sections = {"_preamble": content.strip()[:5000] if content else ""}
    _REQUIRED_DEPLOY_SECTIONS = (
        "Task Summary", "Root Cause", "Recommended Fix", "Affected Files",
    )
    sections_complete = all(
        sidecar_sections.get(k) and str(sidecar_sections.get(k)).strip().lower() not in ("", "n/a")
        for k in _REQUIRED_DEPLOY_SECTIONS
    )
    if not sections_complete:
        logger.error(
            "sections_json_validation_failed task_id=%s source=openclaw — "
            "new artifact missing required sections %s; deploy approval will be blocked",
            task_id, _REQUIRED_DEPLOY_SECTIONS,
        )
    sidecar_path = out_dir / f"{file_prefix}-{task_id}.sections.json"
    sidecar_data = {
        "task_id": task_id,
        "title": title,
        "source": "openclaw",
        "sections": sidecar_sections,
        "sections_complete": sections_complete,
    }
    try:
        path_guard.safe_write_text(
            sidecar_path,
            json.dumps(sidecar_data, indent=2, ensure_ascii=False) + "\n",
            context="agent_callbacks:openclaw_sidecar",
        )
        logger.info("sidecar_write_succeeded task_id=%s path=%s", task_id[:12] if task_id else "?", sidecar_path)
    except Exception as e:
        logger.warning("Failed to write sections sidecar for task %s: %s", task_id, e)

    # No README index write: avoids Permission denied on repo-owned README.md in Docker.
    # Artifacts are per-task (.md + .sections.json); index is optional and not required.

    summary = content.strip()[:200]
    try:
        from app.services.openclaw_client import AGENT_OUTPUT_SECTIONS, INVESTIGATION_SECTIONS
        _check_sections = AGENT_OUTPUT_SECTIONS if use_agent_schema else INVESTIGATION_SECTIONS
    except ImportError:
        _check_sections = (
            "Task Summary", "Root Cause", "Risk Level", "Affected Components",
            "Affected Files", "Recommended Fix", "Testing Plan", "Notes",
        )
    found_sections = [s for s in _check_sections if f"## {s}" in content]
    logger.info(
        "openclaw_apply_success task_id=%s path=%s chars=%d sections=%d use_agent_schema=%s",
        task_id, note_path, len(content), len(found_sections), use_agent_schema,
    )
    # Cost telemetry: log model and token usage per task when gateway provides it (for cost/optimization visibility)
    usage = result.get("usage")
    model_used = result.get("model_used")
    if usage or model_used:
        logger.info(
            "openclaw_apply_cost task_id=%s model_used=%s usage=%s",
            task_id, model_used or "unknown", usage,
        )
    return {"success": True, "summary": f"[OpenClaw] {summary}", "sections": sections}


def _validate_openclaw_note(
    prepared_task: dict[str, Any],
    save_subdir: str,
    file_prefix: str,
    *,
    sections: Optional[tuple[str, ...]] = None,
) -> dict[str, Any]:
    """Validate that an OpenClaw-generated note has real investigation content.

    Checks:
    1. File exists and is non-empty
    2. No fallback/error markers in the content
    3. At least one structured investigation section heading present
    4. Minimum content length (excluding metadata header)
    """
    task_id = _safe_task_id(prepared_task)
    if not task_id:
        return {"success": False, "summary": "missing task.id"}
    note_dir = _note_dir_for_subdir(save_subdir)
    note_path = note_dir / f"{file_prefix}-{task_id}.md"
    ok, msg = _validate_nonempty_markdown(note_path)
    if not ok:
        return {"success": False, "summary": msg}

    content = note_path.read_text(encoding="utf-8")
    content_lower = content.lower()

    for marker in _OPENCLAW_FALLBACK_MARKERS:
        if marker in content_lower:
            logger.warning(
                "openclaw_note_validation: FAILED — fallback marker detected "
                "task_id=%s marker=%r path=%s",
                task_id, marker, note_path,
            )
            return {
                "success": False,
                "summary": f"investigation contains fallback/error marker: '{marker}'",
            }

    # Generic output gate: Root Cause must have actionable content, not filler
    try:
        from app.services.openclaw_client import parse_all_markdown_sections
        parsed_sections = parse_all_markdown_sections(content)
        root_cause = (parsed_sections.get("Root Cause") or "").strip()
        if root_cause:
            rc_lower = root_cause.lower()
            if any(m in rc_lower for m in _GENERIC_INVESTIGATION_MARKERS):
                # Check if Root Cause is ONLY generic filler (no file/function/code path)
                has_concrete = any(
                    x in root_cause for x in (".py", "backend/", "frontend/", "def ", "class ", "line ", ":", "/")
                )
                if not has_concrete or len(root_cause) < 80:
                    logger.warning(
                        "openclaw_note_validation: FAILED — generic Root Cause (no actionable evidence) "
                        "task_id=%s path=%s",
                        task_id, note_path,
                    )
                    return {
                        "success": False,
                        "summary": (
                            "Root Cause lacks actionable evidence. Include exact failing code path, "
                            "module/function, and direct connection between evidence and conclusion. "
                            "Avoid generic phrases like 'further investigation needed' or 'check logs'."
                        ),
                    }
    except Exception as e:
        logger.debug("openclaw_note_validation: generic-output check failed task_id=%s: %s", task_id, e)

    try:
        from app.services.openclaw_client import AGENT_OUTPUT_SECTIONS, INVESTIGATION_SECTIONS
        _agent_sections = AGENT_OUTPUT_SECTIONS
        _inv_sections = INVESTIGATION_SECTIONS
    except ImportError:
        _agent_sections = (
            "Issue Summary", "Scope Reviewed", "Confirmed Facts", "Mismatches",
            "Root Cause", "Proposed Minimal Fix", "Risk Level", "Validation Plan",
            "Cursor Patch Prompt",
        )
        _inv_sections = (
            "Task Summary", "Root Cause", "Risk Level", "Affected Components",
            "Affected Files", "Recommended Fix", "Testing Plan", "Notes",
        )
    use_sections = sections if sections is not None else _inv_sections
    is_agent_schema = sections is not None and set(sections) == set(_agent_sections)
    found_sections = [s for s in use_sections if f"## {s}" in content]
    missing_sections = [s for s in use_sections if s not in found_sections]

    if is_agent_schema:
        # Agent output: require ALL 9 sections
        if missing_sections:
            logger.warning(
                "agent_output_validation: FAILED — missing required sections "
                "task_id=%s missing=%s path=%s",
                task_id, missing_sections, note_path,
            )
            return {
                "success": False,
                "summary": (
                    f"Agent output missing required sections: {', '.join(missing_sections)}. "
                    f"Add each as '## {missing_sections[0]}' (etc.) with content or N/A."
                ),
            }
    elif not found_sections:
        logger.info(
            "openclaw_note_validation: no sections matched task_id=%s expected=%d",
            task_id, len(use_sections),
        )
        # Accept fallback template format (apply_bug_investigation_task) when OpenClaw sections missing
        _fallback_sections = ("Inferred area", "Affected modules", "Relevant docs", "Bug details", "Investigation checklist")
        fallback_found = [s for s in _fallback_sections if f"## {s}" in content]
        if len(fallback_found) >= 2:  # at least Affected modules + one other
            logger.info(
                "openclaw_note_validation: PASSED (fallback template) task_id=%s sections=%s path=%s",
                task_id, fallback_found, note_path,
            )
            found_sections = list(fallback_found)  # for body_len check below
        else:
            logger.warning(
                "openclaw_note_validation: FAILED — no structured sections found "
                "task_id=%s path=%s",
                task_id, note_path,
            )
            return {
                "success": False,
                "summary": (
                    "investigation missing structured sections — expected at least one of: "
                    + ", ".join(use_sections[:4])
                    + ", or fallback template (Affected modules, Relevant docs, Bug details)"
                ),
            }

    body_start = content.find("---")
    body = content[body_start + 3:].strip() if body_start != -1 else content.strip()
    # Use longer of body or preamble for min length — agent callback may append short footer after ---
    preamble = content[:body_start].strip() if body_start != -1 else ""
    body_for_len = max(body, preamble, key=len) if preamble else body
    min_body = _MIN_AGENT_BODY_CHARS if is_agent_schema else _MIN_INVESTIGATION_CONTENT_CHARS
    if len(body_for_len) < min_body:
        logger.warning(
            "openclaw_note_validation: FAILED — content too short "
            "task_id=%s body_len=%d min=%d path=%s",
            task_id, len(body_for_len), min_body, note_path,
        )
        return {
            "success": False,
            "summary": (
                f"Output too short ({len(body_for_len)} chars, minimum {min_body}). "
                "Expand each section with concrete findings and actionable fixes."
            ),
        }

    # Agent schema: require critical sections have meaningful content
    if is_agent_schema:
        try:
            from app.services.openclaw_client import parse_agent_output_sections
            parsed = parse_agent_output_sections(body)
            weak = []
            for sec in _AGENT_CRITICAL_SECTIONS:
                val = (parsed.get(sec) or "").strip()
                if not val:
                    weak.append(sec)
                elif sec == "Risk Level":
                    if len(val) < 3 or ("low" not in val.lower() and "medium" not in val.lower() and "high" not in val.lower() and "n/a" not in val.lower()):
                        weak.append(sec)
                elif val.upper() == "N/A" or len(val) < _AGENT_CRITICAL_MIN_CHARS:
                    weak.append(sec)
            if weak:
                logger.warning(
                    "agent_output_validation: FAILED — critical sections empty or trivial "
                    "task_id=%s weak=%s path=%s",
                    task_id, weak, note_path,
                )
                return {
                    "success": False,
                    "summary": (
                        f"Critical sections need more content: {', '.join(weak)}. "
                        "Each must have concrete findings (not just N/A). "
                        "Root Cause: cite evidence. Proposed Minimal Fix: exact steps. "
                        "Risk Level: LOW/MEDIUM/HIGH + justification. Cursor Patch Prompt: copy-pasteable instruction."
                    ),
                }
        except Exception as e:
            logger.warning("agent_output_validation: section parse failed task_id=%s: %s", task_id, e)

    log_event = "agent_output_validation" if is_agent_schema else "openclaw_note_validation"
    logger.info(
        "%s: PASSED task_id=%s sections=%d body_len=%d path=%s",
        log_event, task_id, len(found_sections), len(body), note_path,
    )
    return {
        "success": True,
        "summary": (
            f"Agent output validated ({len(found_sections)} sections, {len(body)} chars)"
            if is_agent_schema
            else f"OpenClaw investigation validated ({len(found_sections)} sections, {len(body)} chars)"
        ),
    }


def _make_openclaw_callback(
    prompt_builder_fn: Callable,
    save_subdir: str,
    file_prefix: str,
    fallback_fn: Optional[CallbackFn] = None,
    *,
    use_agent_schema: bool = False,
) -> CallbackFn:
    """Factory: return an apply callback that delegates to OpenClaw with a template fallback."""
    def _apply(prepared_task: dict[str, Any]) -> dict[str, Any]:
        return _apply_via_openclaw(
            prepared_task, prompt_builder_fn, save_subdir, file_prefix, fallback_fn,
            use_agent_schema=use_agent_schema,
        )

    setattr(_apply, ATTR_SAFE_LAB_APPLY, True)
    return _apply


def _make_openclaw_validator(
    save_subdir: str,
    file_prefix: str,
    *,
    sections: Optional[tuple[str, ...]] = None,
) -> CallbackFn:
    """Factory: return a validate callback for OpenClaw-generated notes.

    Use sections=AGENT_OUTPUT_SECTIONS for multi-agent operator output.
    """
    def _validate(prepared_task: dict[str, Any]) -> dict[str, Any]:
        return _validate_openclaw_note(
            prepared_task, save_subdir, file_prefix, sections=sections
        )
    return _validate


def _verify_openclaw_solution(
    prepared_task: dict[str, Any],
    save_subdir: str,
    file_prefix: str,
) -> dict[str, Any]:
    """Verify that the OpenClaw output actually addresses the task requirements.

    Uses OpenClaw to evaluate. On FAIL, writes feedback to
    docs/agents/verification-feedback/<task_id>.txt for the next iteration.
    """
    task_id = _safe_task_id(prepared_task)
    if not task_id:
        return {"success": False, "summary": "missing task.id"}

    task = (prepared_task or {}).get("task") or {}
    title = str(task.get("task") or "").strip() or "Untitled"
    details = str(task.get("details") or "").strip()

    note_dir = _note_dir_for_subdir(save_subdir)
    note_path = note_dir / f"{file_prefix}-{task_id}.md"
    if not note_path.exists():
        return {"success": False, "summary": f"note not found: {note_path}"}

    content = note_path.read_text(encoding="utf-8")
    # Skip metadata header for verification
    body_start = content.find("---")
    body = content[body_start + 3:].strip() if body_start != -1 else content.strip()

    # Check for stored feedback (from previous failed verification)
    root = _repo_root()
    feedback_dir = root / "docs" / "agents" / "verification-feedback"
    path_guard.safe_mkdir_lab(feedback_dir, context="agent_callbacks:verification_feedback_dir")
    prev_feedback_path = feedback_dir / f"{task_id}.txt"
    prev_feedback = prev_feedback_path.read_text(encoding="utf-8").strip() if prev_feedback_path.exists() else None

    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    fail_max_attempts = _verification_fail_max_attempts()
    verdict_cache_path = _verification_verdict_cache_path(task_id)
    cached_verdict: dict[str, Any] = {}
    if verdict_cache_path.exists():
        try:
            cached_verdict = json.loads(verdict_cache_path.read_text(encoding="utf-8"))
        except Exception:
            cached_verdict = {}

    cached_hash = str(cached_verdict.get("body_hash") or "").strip()
    cached_verdict_value = str(cached_verdict.get("verdict") or "").strip().upper()
    cached_reason = str(cached_verdict.get("reason") or "").strip()
    try:
        cached_fail_attempts = int(cached_verdict.get("fail_attempts") or 0)
    except (TypeError, ValueError):
        cached_fail_attempts = 0

    if cached_hash == body_hash and cached_verdict_value == "PASS":
        return {
            "success": True,
            "summary": f"Solution verified (cached): {cached_reason or 'addresses task requirements'}",
        }

    if cached_hash == body_hash and cached_verdict_value == "FAIL" and cached_fail_attempts >= fail_max_attempts:
        return {
            "success": False,
            "summary": f"Solution does not address requirements (unchanged output): {cached_reason or 'verification failed'}",
            "verification_feedback": cached_reason or "verification failed",
        }

    try:
        from app.services.openclaw_client import verify_solution_against_task
        passed, reason = verify_solution_against_task(
            title, details, body,
            task_id=task_id,
            previous_feedback=prev_feedback,
        )
    except Exception as e:
        logger.warning("verify_solution_against_task failed task_id=%s: %s", task_id, e)
        return {"success": False, "summary": f"verification error: {e}"}

    if passed:
        try:
            path_guard.safe_write_text(
                verdict_cache_path,
                json.dumps(
                    {
                        "task_id": task_id,
                        "body_hash": body_hash,
                        "verdict": "PASS",
                        "reason": reason or "addresses task requirements",
                        "fail_attempts": 0,
                    },
                    indent=2,
                    ensure_ascii=False,
                ) + "\n",
                context="agent_callbacks:verification_verdict_cache_pass",
            )
        except Exception as cache_err:
            logger.debug("verification verdict cache write failed task_id=%s: %s", task_id, cache_err)
        return {"success": True, "summary": f"Solution verified: {reason or 'addresses task requirements'}"}

    # Unavailable: environment/config issue — do NOT write feedback (not investigative failure)
    _unavailable_prefix = "verification unavailable:"
    if (reason or "").strip().lower().startswith(_unavailable_prefix.lower()):
        return {
            "success": False,
            "summary": (reason or "").strip(),
            "unavailable": True,
            "unavailable_reason": (reason or "").strip(),
        }

    # FAIL: actual content failure — write feedback for next iteration
    try:
        path_guard.safe_write_text(
            feedback_dir / f"{task_id}.txt",
            reason or "Output does not address task requirements",
            context="agent_callbacks:verification_feedback",
        )
    except Exception as e:
        logger.warning("Could not write verification feedback for task %s: %s", task_id, e)

    fail_attempts = 1
    if cached_hash == body_hash and cached_verdict_value == "FAIL":
        fail_attempts = cached_fail_attempts + 1

    try:
        path_guard.safe_write_text(
            verdict_cache_path,
            json.dumps(
                {
                    "task_id": task_id,
                    "body_hash": body_hash,
                    "verdict": "FAIL",
                    "reason": reason or "output does not address task requirements",
                    "fail_attempts": fail_attempts,
                },
                indent=2,
                ensure_ascii=False,
            ) + "\n",
            context="agent_callbacks:verification_verdict_cache_fail",
        )
    except Exception as cache_err:
        logger.debug("verification verdict cache write failed task_id=%s: %s", task_id, cache_err)

    return {
        "success": False,
        "summary": f"Solution does not address requirements: {reason}",
        "verification_feedback": reason,
    }


def _make_openclaw_verifier(save_subdir: str, file_prefix: str) -> CallbackFn:
    """Factory: return a verify_solution callback for OpenClaw-generated notes."""
    def _verify(prepared_task: dict[str, Any]) -> dict[str, Any]:
        return _verify_openclaw_solution(prepared_task, save_subdir, file_prefix)
    return _verify


def select_default_callbacks_for_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    """
    Select a safe default callback pack based on prepared_task content.

    Returns:
        {
          "apply_change_fn": callable | None,
          "validate_fn": callable | None,
          "deploy_fn": None,
          "selection_reason": "..."
        }
    """
    task_obj = (prepared_task or {}).get("task") or {}
    _task_type_raw = str(task_obj.get("type") or "")
    _task_type = _task_type_raw.strip().lower()
    _task_title = str(task_obj.get("task") or "")[:80]
    logger.info(
        "select_default_callbacks_for_task: task_type_raw=%r task_type_normalized=%r title=%r",
        _task_type_raw, _task_type, _task_title,
    )

    # ── Explicit Type field override (highest priority) ──────────────
    # Notion Type="bug", "investigation", or "architecture investigation" maps to the
    # bug investigation pack with manual_only=True. This ensures investigation tasks
    # are never misclassified and always produce the expected artifact at
    # docs/agents/bug-investigations/notion-bug-{id}.md.
    if _task_type in ("bug", "bugfix", "bug fix", "investigation", "architecture investigation"):
        logger.info(
            "select_default_callbacks_for_task: explicit bug type detected — "
            "selecting bug_investigation pack (extended lifecycle) "
            "task_type_raw=%r task_type_normalized=%r title=%r",
            _task_type_raw, _task_type, _task_title,
        )
        from app.services.openclaw_client import build_investigation_prompt
        return {
            "apply_change_fn": _make_openclaw_callback(
                build_investigation_prompt,
                "docs/agents/bug-investigations", "notion-bug",
                fallback_fn=apply_bug_investigation_task,
            ),
            "validate_fn": _make_openclaw_validator("docs/agents/bug-investigations", "notion-bug"),
            "verify_solution_fn": _make_openclaw_verifier("docs/agents/bug-investigations", "notion-bug"),
            "deploy_fn": None,
            "manual_only": True,
            GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
            "selection_reason": f"bug investigation task (Notion Type raw={_task_type_raw!r} normalized={_task_type!r} — explicit match; approval-gated)",
        }

    # ── Multi-agent routing (Telegram, Execution) ───────────────────
    # Specialized agents for analysis/diagnosis; use shared output schema.
    try:
        from app.services.agent_routing import (
            AGENT_EXECUTION_STATE,
            AGENT_TELEGRAM_ALERTS,
            get_file_prefix,
            get_save_subdir,
            route_task_with_reason,
        )
        from app.services.openclaw_client import (
            AGENT_OUTPUT_SECTIONS,
            build_execution_state_prompt,
            build_telegram_alerts_prompt,
        )
        agent_id, route_reason = route_task_with_reason(prepared_task)
        if agent_id == AGENT_TELEGRAM_ALERTS:
            save_subdir = get_save_subdir(agent_id)
            file_prefix = get_file_prefix(agent_id)
            logger.info(
                "agent_selected agent=telegram_alerts route_reason=%s task_id=%s title=%r",
                route_reason, task_obj.get("id", ""), _task_title,
            )
            return {
                "apply_change_fn": _make_openclaw_callback(
                    build_telegram_alerts_prompt,
                    save_subdir, file_prefix,
                    use_agent_schema=True,
                    fallback_fn=apply_bug_investigation_task,
                ),
                "validate_fn": _make_openclaw_validator(
                    save_subdir, file_prefix, sections=AGENT_OUTPUT_SECTIONS
                ),
                "verify_solution_fn": _make_openclaw_verifier(save_subdir, file_prefix),
                "deploy_fn": None,
                "manual_only": True,
                GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
                "selection_reason": "Telegram and Alerts agent (multi-agent operator; approval-gated)",
            }
        if agent_id == AGENT_EXECUTION_STATE:
            save_subdir = get_save_subdir(agent_id)
            file_prefix = get_file_prefix(agent_id)
            logger.info(
                "agent_selected agent=execution_state route_reason=%s task_id=%s title=%r",
                route_reason, task_obj.get("id", ""), _task_title,
            )
            return {
                "apply_change_fn": _make_openclaw_callback(
                    build_execution_state_prompt,
                    save_subdir, file_prefix,
                    use_agent_schema=True,
                    fallback_fn=apply_bug_investigation_task,
                ),
                "validate_fn": _make_openclaw_validator(
                    save_subdir, file_prefix, sections=AGENT_OUTPUT_SECTIONS
                ),
                "verify_solution_fn": _make_openclaw_verifier(save_subdir, file_prefix),
                "deploy_fn": None,
                "manual_only": True,
                GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
                "selection_reason": "Execution and State agent (multi-agent operator; approval-gated)",
            }
        if agent_id is not None:
            logger.info(
                "agent_routing_fallback agent=%s route_reason=%s — no handler (scaffolded), falling through",
                agent_id, route_reason,
            )
    except Exception as e:
        logger.warning(
            "agent_routing_init_failed error=%s — falling through to next callback. "
            "Diagnostic: ensure agent_routing and openclaw_client import (httpx, etc.).",
            e,
            exc_info=True,
        )

    if _is_documentation_eligible(prepared_task):
        from app.services.openclaw_client import build_documentation_prompt
        return {
            "apply_change_fn": _make_openclaw_callback(
                build_documentation_prompt,
                "docs/agents/generated-notes", "notion-task",
                fallback_fn=apply_documentation_task,
            ),
            "validate_fn": _make_openclaw_validator("docs/agents/generated-notes", "notion-task"),
            "verify_solution_fn": _make_openclaw_verifier("docs/agents/generated-notes", "notion-task"),
            "deploy_fn": None,
            GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
            "selection_reason": "documentation task (OpenClaw AI analysis with template fallback)",
        }

    if _is_monitoring_triage_eligible(prepared_task):
        from app.services.openclaw_client import build_monitoring_prompt
        return {
            "apply_change_fn": _make_openclaw_callback(
                build_monitoring_prompt,
                "docs/runbooks/triage", "notion-triage",
                fallback_fn=apply_monitoring_triage_task,
            ),
            "validate_fn": _make_openclaw_validator("docs/runbooks/triage", "notion-triage"),
            "verify_solution_fn": _make_openclaw_verifier("docs/runbooks/triage", "notion-triage"),
            "deploy_fn": None,
            GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
            "selection_reason": "monitoring triage task (OpenClaw AI analysis with template fallback)",
        }

    if _is_bug_investigation_eligible(prepared_task):
        logger.info(
            "select_default_callbacks_for_task: matched bug_investigation via keyword heuristics "
            "(extended lifecycle) task_type_raw=%r task_type_normalized=%r title=%r",
            _task_type_raw, _task_type, _task_title,
        )
        from app.services.openclaw_client import build_investigation_prompt
        return {
            "apply_change_fn": _make_openclaw_callback(
                build_investigation_prompt,
                "docs/agents/bug-investigations", "notion-bug",
                fallback_fn=apply_bug_investigation_task,
            ),
            "validate_fn": _make_openclaw_validator("docs/agents/bug-investigations", "notion-bug"),
            "verify_solution_fn": _make_openclaw_verifier("docs/agents/bug-investigations", "notion-bug"),
            "deploy_fn": None,
            "manual_only": True,
            GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
            "selection_reason": "bug investigation task (keyword heuristic match; approval-gated)",
        }

    if _is_profile_setting_analysis_eligible(prepared_task):
        try:
            from app.services.profile_setting_analysis import (
                apply_profile_setting_analysis_task,
                profile_setting_preview_metadata,
                validate_profile_setting_analysis_task,
            )
            preview = profile_setting_preview_metadata(prepared_task)
            if preview:
                prepared_task.setdefault("versioning", {})
                prepared_task["versioning"].update(
                    {
                        "symbol": preview.get("symbol", ""),
                        "profile": preview.get("profile", ""),
                        "side": preview.get("side", ""),
                    }
                )
                task_obj = prepared_task.get("task") or {}
                task_obj["symbol"] = preview.get("symbol", "")
                task_obj["profile"] = preview.get("profile", "")
                task_obj["side"] = preview.get("side", "")
            return {
                "apply_change_fn": apply_profile_setting_analysis_task,
                "validate_fn": validate_profile_setting_analysis_task,
                "deploy_fn": None,
                "manual_only": True,
                GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PROD_MUTATION,
                "selection_reason": "profile-setting-analysis task (analysis-only per-symbol/profile/side proposal; approval-gated)",
            }
        except Exception as e:
            logger.warning("profile setting analysis callbacks unavailable (falling through): %s", e)

    # Strategy patch callback is heavily constrained and manual-only.
    # It is selected only when strict eligibility passes in agent_strategy_patch.
    try:
        from app.services.agent_strategy_patch import (
            apply_strategy_patch_task,
            strategy_patch_preview_metadata,
            validate_strategy_patch_task,
        )
        patch_meta = strategy_patch_preview_metadata(prepared_task)
        if patch_meta:
            # Enrich prepared metadata for approval summary visibility.
            prepared_task.setdefault("versioning", {})
            prepared_task["versioning"].update(
                {
                    "current_version": patch_meta.get("current_version", ""),
                    "proposed_version": patch_meta.get("proposed_version", ""),
                    "change_summary": patch_meta.get("change_summary", ""),
                    "confidence_score": patch_meta.get("confidence_score", ""),
                    "risk_level": patch_meta.get("risk_level", ""),
                }
            )
            task_obj = prepared_task.get("task") or {}
            task_obj["current_version"] = patch_meta.get("current_version", "")
            task_obj["proposed_version"] = patch_meta.get("proposed_version", "")
            task_obj["change_summary"] = patch_meta.get("change_summary", "")
            task_obj["confidence_score"] = patch_meta.get("confidence_score", "")
            return {
                "apply_change_fn": apply_strategy_patch_task,
                "validate_fn": validate_strategy_patch_task,
                "deploy_fn": None,
                "manual_only": True,
                GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PROD_MUTATION,
                "selection_reason": "strategy-patch task (controlled allowlisted business-logic tuning; approval-gated manual execution only)",
            }
    except Exception as e:
        logger.debug("strategy patch callbacks unavailable: %s", e)

    if _is_signal_performance_analysis_eligible(prepared_task):
        try:
            from app.services.signal_performance_analysis import (
                apply_signal_performance_analysis_task,
                validate_signal_performance_analysis_task,
            )
            return {
                "apply_change_fn": apply_signal_performance_analysis_task,
                "validate_fn": validate_signal_performance_analysis_task,
                "deploy_fn": None,
                "manual_only": True,
                GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
                "selection_reason": "signal-performance-analysis task (analysis-only historical outcome proposal; approval-gated)",
            }
        except Exception as e:
            logger.warning("signal performance analysis callbacks unavailable (falling through): %s", e)

    if _is_strategy_analysis_eligible(prepared_task):
        try:
            from app.services.agent_strategy_analysis import (
                apply_strategy_analysis_task,
                validate_strategy_analysis_task,
            )
            return {
                "apply_change_fn": apply_strategy_analysis_task,
                "validate_fn": validate_strategy_analysis_task,
                "deploy_fn": None,
                "manual_only": True,
                GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
                "selection_reason": "strategy-analysis task (analysis-only proposal for alert/signal/threshold tuning; requires approval gate)",
            }
        except Exception as e:
            logger.warning("strategy analysis callbacks unavailable (falling through): %s", e)

    # No specific callback matched — try OpenClaw with a generic prompt as last resort
    try:
        from app.services.openclaw_client import build_generic_prompt, is_openclaw_configured
        if is_openclaw_configured():
            logger.info(
                "select_default_callbacks_for_task: no specific match, using generic OpenClaw "
                "task_type_raw=%r task_type_normalized=%r title=%r",
                _task_type_raw, _task_type, _task_title,
            )
            return {
                "apply_change_fn": _make_openclaw_callback(
                    build_generic_prompt,
                    "docs/agents/generated-notes", "notion-task",
                ),
                "validate_fn": _make_openclaw_validator("docs/agents/generated-notes", "notion-task"),
                "deploy_fn": None,
                GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
                "selection_reason": "generic OpenClaw analysis (no specific callback matched)",
            }
    except Exception as e:
        logger.debug("openclaw generic fallback unavailable: %s", e)

    logger.warning(
        "select_default_callbacks_for_task: NO callback matched — returning None apply_change_fn "
        "task_type_raw=%r task_type_normalized=%r title=%r",
        _task_type_raw, _task_type, _task_title,
    )
    return {
        "apply_change_fn": None,
        "validate_fn": None,
        "deploy_fn": None,
        "selection_reason": "no safe default callbacks for this task type/area",
    }


setattr(apply_bug_investigation_task, ATTR_SAFE_LAB_APPLY, True)
setattr(apply_documentation_task, ATTR_SAFE_LAB_APPLY, True)
setattr(apply_monitoring_triage_task, ATTR_SAFE_LAB_APPLY, True)
