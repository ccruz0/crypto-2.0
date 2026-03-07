"""
First minimal callback pack for safe agent execution.

These callbacks are intentionally low-risk:
- Documentation tasks: create/update small notes and index references under /docs
- Monitoring triage tasks: create/update incident triage notes under /docs (no runtime changes)

No shell execution, no commits, no deployment, and no trading/exchange/order lifecycle changes.
All functions return structured dicts (success/summary) and avoid raising where practical.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


CallbackFn = Callable[[dict[str, Any]], dict[str, Any]]


def _repo_root() -> Path:
    """Return the repository / project root directory.

    Local layout:  <repo>/backend/app/services/agent_callbacks.py  -> parents[3]
    Docker layout: /app/app/services/agent_callbacks.py            -> parents[2]

    Uses .git as the definitive marker locally. In Docker (.git absent),
    falls back to the shallowest ancestor that contains a ``docs/`` dir.
    """
    here = Path(__file__).resolve()
    # .git is the definitive repo root marker (available locally, not in Docker)
    for ancestor in here.parents:
        if (ancestor / ".git").is_dir():
            return ancestor
    # Docker: no .git — try parents[3] first, then parents[2] (typical Docker /app)
    for idx in (3, 2):
        if idx < len(here.parents) and (here.parents[idx] / "docs").is_dir():
            return here.parents[idx]
    # Final fallback
    return here.parents[min(2, len(here.parents) - 1)]


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
    """
    content = md_path.read_text(encoding="utf-8")
    targets = _markdown_links(content)
    for t in targets:
        if not t or "://" in t:
            continue
        if t.startswith("#"):
            continue
        # Strip anchors from relative links: foo.md#section
        t_clean = t.split("#", 1)[0]
        if not t_clean:
            continue
        resolved = (md_path.parent / t_clean).resolve()
        if not resolved.exists():
            return False, f"broken relative link target: {t} (resolved to {resolved.as_posix()})"
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

        # Build relative links (from generated-notes/ directory) to existing docs.
        def rel_link(target_repo_path: str) -> str:
            target = (root / target_repo_path).resolve()
            try:
                rel = target.relative_to(notes_dir)
            except Exception:
                rel = Path(target_repo_path)
            return rel.as_posix()

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
                rel = target.relative_to(from_dir)
            except Exception:
                rel = Path(target_repo_path)
            return rel.as_posix()

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

        inv_dir = root / "docs" / "agents" / "bug-investigations"
        _ensure_dir(inv_dir)

        note_path = inv_dir / f"notion-bug-{task_id}.md"
        idx_path = inv_dir / "README.md"

        def rel_link(from_dir: Path, target_repo_path: str) -> str:
            target = (root / target_repo_path).resolve()
            try:
                rel = target.relative_to(from_dir)
            except Exception:
                rel = Path(target_repo_path)
            return rel.as_posix()

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

        return {
            "success": True,
            "summary": f"bug investigation note prepared at docs/agents/bug-investigations/notion-bug-{task_id}.md",
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

        root = _repo_root()
        note_path = root / "docs" / "agents" / "bug-investigations" / f"notion-bug-{task_id}.md"

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
    _task_type = str(task_obj.get("type") or "").lower()
    _task_title = str(task_obj.get("task") or "")[:80]
    logger.debug("select_default_callbacks_for_task: type=%r title=%r", _task_type, _task_title)

    if _is_documentation_eligible(prepared_task):
        return {
            "apply_change_fn": apply_documentation_task,
            "validate_fn": validate_documentation_task,
            "deploy_fn": None,
            "selection_reason": "documentation-like task (docs/runbooks/agent docs keywords)",
        }

    if _is_monitoring_triage_eligible(prepared_task):
        return {
            "apply_change_fn": apply_monitoring_triage_task,
            "validate_fn": validate_monitoring_triage_task,
            "deploy_fn": None,
            "selection_reason": "monitoring/infrastructure triage task (monitoring keywords or inferred monitoring-infra area)",
        }

    # Bug investigation: check early (type-based match is reliable and should not
    # be shadowed by broad keyword-based analysis checks below that may fail imports).
    if _is_bug_investigation_eligible(prepared_task):
        logger.info("select_default_callbacks_for_task: matched bug_investigation type=%r title=%r", _task_type, _task_title)
        return {
            "apply_change_fn": apply_bug_investigation_task,
            "validate_fn": validate_bug_investigation_task,
            "deploy_fn": None,
            "manual_only": True,
            "selection_reason": "bug investigation task (documentation-only investigation note; approval-gated)",
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

    logger.warning(
        "select_default_callbacks_for_task: NO callback matched type=%r title=%r — returning None apply_change_fn",
        _task_type, _task_title,
    )
    return {
        "apply_change_fn": None,
        "validate_fn": None,
        "deploy_fn": None,
        "selection_reason": "no safe default callbacks for this task type/area",
    }

