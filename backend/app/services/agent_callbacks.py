"""
First minimal callback pack for safe agent execution.

These callbacks are intentionally low-risk:
- Documentation tasks: create/update small notes and index references under /docs
- Monitoring triage tasks: create/update incident triage notes under /docs (no runtime changes)

No shell execution, no commits, no deployment, and no trading/exchange/order lifecycle changes.
All functions return structured dicts (success/summary) and avoid raising where practical.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


CallbackFn = Callable[[dict[str, Any]], dict[str, Any]]


def _repo_root() -> Path:
    from app.services._paths import workspace_root
    return workspace_root()


def _note_dir_for_subdir(save_subdir: str) -> Path:
    """Return writable directory for notes; use bug-investigations fallback when repo path not writable."""
    if save_subdir == "docs/agents/bug-investigations":
        from app.services._paths import get_writable_bug_investigations_dir
        return get_writable_bug_investigations_dir()
    return _repo_root() / save_subdir


def _safe_task_id(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("id") or "").strip()


def _safe_task_title(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("task") or "").strip()


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write_if_missing(path: Path, contents: str) -> bool:
    """
    Create file if missing. Return True if created, False if already existed.
    """
    if path.exists():
        return False
    path.write_text(contents, encoding="utf-8")
    return True


def _append_line_if_missing(path: Path, line: str) -> bool:
    """
    Append a single line to a file if the exact line is not already present.
    Creates the file if needed. Returns True if it appended or created, else False.
    """
    if not path.exists():
        path.write_text(line.rstrip() + "\n", encoding="utf-8")
        return True
    existing = path.read_text(encoding="utf-8")
    if line in existing:
        return False
    with path.open("a", encoding="utf-8") as f:
        if not existing.endswith("\n"):
            f.write("\n")
        f.write(line.rstrip() + "\n")
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

    if task_type in ("bug", "bugfix", "bug fix"):
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

        note_path = inv_dir / f"notion-bug-{task_id}.md"
        idx_path = inv_dir / "README.md"

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

        created = _write_if_missing(note_path, note_contents)
        if not created:
            _append_line_if_missing(
                note_path,
                "\n---\n\n- Investigation note touched by agent callback (no overwrite).\n",
            )

        idx_header = (
            "# Bug investigations (agent)\n\n"
            "Structured investigation notes for bug-type tasks.\n"
            "These are documentation-only and must not change runtime behavior.\n\n"
        )
        _write_if_missing(idx_path, idx_header)
        idx_line = f"- [Notion bug {task_id}: {title}](notion-bug-{task_id}.md)"
        _append_line_if_missing(idx_path, idx_line)

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

        inv_dir = _writable_bug_investigations_dir()
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

_MIN_INVESTIGATION_CONTENT_CHARS = 200

_OPENCLAW_MAX_RETRIES = 1
_OPENCLAW_RETRY_DELAY_S = 5


def _call_openclaw_once(
    send_to_openclaw: Callable,
    user_prompt: str,
    instructions: str,
    task_id: str,
    model_chain_override: list[str] | None = None,
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
    found_sections = [s for s in INVESTIGATION_SECTIONS if f"## {s}" in content]
    if not found_sections and len(content.strip()) < _MIN_INVESTIGATION_CONTENT_CHARS:
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
) -> dict[str, Any]:
    """Send a task to OpenClaw for AI analysis, save the result, fall back to template on failure."""
    task_id = _safe_task_id(prepared_task)
    title = _safe_task_title(prepared_task) or "Untitled"

    try:
        from app.services.openclaw_client import is_openclaw_configured, send_to_openclaw
    except Exception as e:
        logger.warning("openclaw_client import failed: %s — using fallback", e)
        if fallback_fn:
            return fallback_fn(prepared_task)
        return {"success": False, "summary": f"openclaw_client unavailable: {e}"}

    if not is_openclaw_configured():
        logger.info("OpenClaw not configured — using template fallback for task %s", task_id)
        if fallback_fn:
            return fallback_fn(prepared_task)
        return {"success": False, "summary": "OPENCLAW_API_TOKEN not configured"}

    try:
        user_prompt, instructions = prompt_builder_fn(prepared_task)
    except Exception as e:
        logger.warning("OpenClaw prompt build failed for task %s: %s", task_id, e)
        if fallback_fn:
            return fallback_fn(prepared_task)
        return {"success": False, "summary": f"prompt build error: {e}"}

    # Append verification feedback if this is a re-investigation after failed verification
    root = _repo_root()
    feedback_path = root / "docs" / "agents" / "verification-feedback" / f"{task_id}.txt"
    if feedback_path.exists():
        try:
            prev_feedback = feedback_path.read_text(encoding="utf-8").strip()
            if prev_feedback:
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

    for attempt in range(1, max_attempts + 1):
        result, last_error = _call_openclaw_once(
            send_to_openclaw, user_prompt, instructions, task_id,
            model_chain_override=chain_override,
        )
        if result is not None:
            break
        if attempt < max_attempts:
            logger.warning(
                "OpenClaw attempt %d/%d failed for task %s: %s — retrying in %ds",
                attempt, max_attempts, task_id, last_error, _OPENCLAW_RETRY_DELAY_S,
            )
            time.sleep(_OPENCLAW_RETRY_DELAY_S)
        else:
            logger.warning(
                "OpenClaw attempt %d/%d failed for task %s: %s — no retries left",
                attempt, max_attempts, task_id, last_error,
            )

    if result is None:
        if fallback_fn:
            return fallback_fn(prepared_task)
        return {"success": False, "summary": last_error}

    content = result.get("content") or ""

    # Parse structured sections (gracefully returns None values for missing ones)
    try:
        from app.services.openclaw_client import parse_investigation_sections
        sections = parse_investigation_sections(content)
    except Exception:
        sections = {}

    # Stash sections on prepared_task for downstream metadata enrichment
    if sections:
        prepared_task["_openclaw_sections"] = sections

    out_dir = _note_dir_for_subdir(save_subdir)
    _ensure_dir(out_dir)

    note_path = out_dir / f"{file_prefix}-{task_id}.md"
    note_contents = (
        f"# {title}\n\n"
        f"- **Notion page id**: `{task_id}`\n"
        f"- **Source**: OpenClaw AI analysis\n\n"
        f"---\n\n"
        f"{content}\n"
    )

    note_path.write_text(note_contents, encoding="utf-8")

    # Save parsed sections as JSON sidecar for downstream consumption
    if sections:
        sidecar_path = out_dir / f"{file_prefix}-{task_id}.sections.json"
        sidecar_data = {
            "task_id": task_id,
            "title": title,
            "source": "openclaw",
            "sections": sections,
        }
        try:
            sidecar_path.write_text(
                json.dumps(sidecar_data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            logger.info("Structured sections sidecar saved at %s", sidecar_path)
        except Exception as e:
            logger.warning("Failed to write sections sidecar for task %s: %s", task_id, e)

    idx_path = out_dir / "README.md"
    idx_line = f"- [{file_prefix} {task_id}: {title}]({file_prefix}-{task_id}.md)"
    if not idx_path.exists():
        idx_path.write_text(f"# AI analysis notes\n\n{idx_line}\n", encoding="utf-8")
    else:
        _append_line_if_missing(idx_path, idx_line)

    summary = content.strip()[:200]
    from app.services.openclaw_client import INVESTIGATION_SECTIONS
    found_sections = [s for s in INVESTIGATION_SECTIONS if f"## {s}" in content]
    logger.info("OpenClaw analysis saved for task %s at %s (%d chars, sections=%d)", task_id, note_path, len(content), len(found_sections))
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

    from app.services.openclaw_client import INVESTIGATION_SECTIONS
    found_sections = [s for s in INVESTIGATION_SECTIONS if f"## {s}" in content]
    if not found_sections:
        logger.warning(
            "openclaw_note_validation: FAILED — no structured sections found "
            "task_id=%s path=%s",
            task_id, note_path,
        )
        return {
            "success": False,
            "summary": (
                "investigation missing structured sections — expected at least one of: "
                + ", ".join(INVESTIGATION_SECTIONS[:4])
            ),
        }

    body_start = content.find("---")
    body = content[body_start + 3:].strip() if body_start != -1 else content.strip()
    if len(body) < _MIN_INVESTIGATION_CONTENT_CHARS:
        logger.warning(
            "openclaw_note_validation: FAILED — content too short "
            "task_id=%s body_len=%d min=%d path=%s",
            task_id, len(body), _MIN_INVESTIGATION_CONTENT_CHARS, note_path,
        )
        return {
            "success": False,
            "summary": (
                f"investigation content too short ({len(body)} chars, "
                f"minimum {_MIN_INVESTIGATION_CONTENT_CHARS})"
            ),
        }

    logger.info(
        "openclaw_note_validation: PASSED task_id=%s sections=%d body_len=%d path=%s",
        task_id, len(found_sections), len(body), note_path,
    )
    return {
        "success": True,
        "summary": (
            f"OpenClaw investigation validated "
            f"({len(found_sections)} sections, {len(body)} chars)"
        ),
    }


def _make_openclaw_callback(
    prompt_builder_fn: Callable,
    save_subdir: str,
    file_prefix: str,
    fallback_fn: Optional[CallbackFn] = None,
) -> CallbackFn:
    """Factory: return an apply callback that delegates to OpenClaw with a template fallback."""
    def _apply(prepared_task: dict[str, Any]) -> dict[str, Any]:
        return _apply_via_openclaw(
            prepared_task, prompt_builder_fn, save_subdir, file_prefix, fallback_fn,
        )
    return _apply


def _make_openclaw_validator(save_subdir: str, file_prefix: str) -> CallbackFn:
    """Factory: return a validate callback for OpenClaw-generated notes."""
    def _validate(prepared_task: dict[str, Any]) -> dict[str, Any]:
        return _validate_openclaw_note(prepared_task, save_subdir, file_prefix)
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
    feedback_dir = root / "docs" / "agents" / "verification-feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    prev_feedback_path = feedback_dir / f"{task_id}.txt"
    prev_feedback = prev_feedback_path.read_text(encoding="utf-8").strip() if prev_feedback_path.exists() else None

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
        return {"success": True, "summary": f"Solution verified: {reason or 'addresses task requirements'}"}

    # FAIL: write feedback for next iteration
    try:
        (feedback_dir / f"{task_id}.txt").write_text(reason or "Output does not address task requirements", encoding="utf-8")
    except Exception as e:
        logger.warning("Could not write verification feedback for task %s: %s", task_id, e)

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
    # Notion Type="bug" always maps to the bug investigation pack with
    # manual_only=True, regardless of keyword heuristics.  This ensures
    # bug tasks are never misclassified as documentation, monitoring, or
    # generic OpenClaw and always enter the extended lifecycle.
    if _task_type in ("bug", "bugfix", "bug fix"):
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
            "selection_reason": f"bug investigation task (Notion Type raw={_task_type_raw!r} normalized={_task_type!r} — explicit match; approval-gated)",
        }

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

