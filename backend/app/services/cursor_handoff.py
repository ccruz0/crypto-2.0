"""
Cursor implementation handoff prompt builder.

Converts a completed OpenClaw investigation into a structured, Cursor-ready
implementation prompt.  Reuses structured investigation sections (Task Summary,
Root Cause, Affected Files, Recommended Fix, Testing Plan) when available and
degrades gracefully to best-effort extraction from free-form reports.

The generated prompt is saved as a markdown file under
``docs/agents/cursor-handoffs/`` and optionally stashed on the prepared_task
dict for immediate downstream use.

No network calls, no Notion writes, no side effects beyond writing the
handoff file.  Safe to call from the executor or from a Telegram callback.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Fixed constraints included in every Cursor handoff prompt.
_CURSOR_CONSTRAINTS = (
    "- Build on the current implementation\n"
    "- Change only the parts needed\n"
    "- Keep the rest untouched\n"
    "- Do not refactor unrelated code\n"
    "- Preserve existing architecture unless explicitly required"
)


def _repo_root() -> Path:
    from app.services._paths import workspace_root
    return workspace_root()


def _section_text(sections: dict[str, Any], key: str, fallback: str = "") -> str:
    """Return a section value as a trimmed string, or *fallback* if absent/N-A."""
    raw = sections.get(key)
    if raw is None:
        return fallback
    text = str(raw).strip()
    if text.lower() in ("", "n/a"):
        return fallback
    return text


def _extract_file_list(sections: dict[str, Any]) -> list[str]:
    """Pull individual file paths from the Affected Files section."""
    raw = _section_text(sections, "Affected Files")
    if not raw:
        return []
    files: list[str] = []
    for line in raw.splitlines():
        cleaned = line.strip().lstrip("-*•` ").rstrip("` ")
        if cleaned and ("/" in cleaned or cleaned.endswith(".py") or cleaned.endswith(".ts") or cleaned.endswith(".tsx")):
            files.append(cleaned)
    return files


# ------------------------------------------------------------------
# Core builder
# ------------------------------------------------------------------


def build_cursor_handoff_prompt(
    task_title: str,
    sections: dict[str, Any],
    *,
    task_id: str = "",
    repo_area: dict[str, Any] | None = None,
    extra_constraints: str = "",
) -> str:
    """Build a Cursor-ready implementation prompt from OpenClaw sections.

    Parameters
    ----------
    task_title:
        Human-readable task name (used as the ``Task`` heading).
    sections:
        Parsed investigation sections dict (from ``parse_investigation_sections``
        or loaded from ``.sections.json``).  When empty or all-None the builder
        falls back to the ``_preamble`` key (free-form legacy report).
    task_id:
        Optional Notion page ID for traceability.
    repo_area:
        Optional inferred repo area dict (``area_name``, ``likely_files``, etc.).
    extra_constraints:
        Additional constraint lines appended after the fixed set.

    Returns
    -------
    str
        The complete Cursor handoff prompt as a markdown string.
    """
    sections = sections or {}
    repo_area = repo_area or {}

    # --- Task ---
    task_line = (task_title or "").strip() or "(untitled)"
    if task_id:
        task_line += f"  (Notion: `{task_id}`)"

    # --- Repo / affected area ---
    repo_line = _section_text(sections, "Affected Components")
    if not repo_line:
        repo_line = str(repo_area.get("area_name") or "").strip() or "(see affected files)"

    # --- Root cause ---
    root_cause = _section_text(sections, "Root Cause")
    if not root_cause:
        preamble = _section_text(sections, "_preamble")
        if preamble:
            root_cause = preamble[:600]
            if len(preamble) > 600:
                root_cause += "\n…(truncated from free-form report)"
        else:
            root_cause = "(not determined — manual investigation required)"

    # --- Affected files ---
    file_list = _extract_file_list(sections)
    if not file_list:
        likely = repo_area.get("likely_files") or []
        file_list = list(likely[:12])
    if file_list:
        affected_block = "\n".join(f"- `{f}`" for f in file_list)
    else:
        affected_block = "- (none identified — locate the relevant files before patching)"

    # --- Constraints ---
    constraints_block = _CURSOR_CONSTRAINTS
    if extra_constraints and extra_constraints.strip():
        constraints_block += "\n" + extra_constraints.strip()

    # --- Expected outcome ---
    fix = _section_text(sections, "Recommended Fix")
    if not fix:
        task_summary = _section_text(sections, "Task Summary")
        fix = task_summary if task_summary else "(apply the smallest safe fix for the root cause described above)"

    # --- Testing requirements ---
    testing = _section_text(sections, "Testing Plan")
    if not testing:
        testing = (
            "- Verify the fix resolves the reported issue\n"
            "- Run existing tests / linter to confirm no regressions\n"
            "- Manual smoke-test if automated coverage is insufficient"
        )

    # --- Assemble ---
    prompt = (
        f"## Task\n\n{task_line}\n\n"
        f"## Repo\n\n{repo_line}\n\n"
        f"## Root cause\n\n{root_cause}\n\n"
        f"## Affected files\n\n{affected_block}\n\n"
        f"## Constraints\n\n{constraints_block}\n\n"
        f"## Expected outcome\n\n{fix}\n\n"
        f"## Testing requirements\n\n{testing}\n"
    )
    return prompt


# ------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------

_HANDOFF_SUBDIR = "docs/agents/cursor-handoffs"


def save_cursor_handoff(
    task_id: str,
    prompt: str,
    title: str = "",
) -> Path | None:
    """Write the handoff prompt to ``docs/agents/cursor-handoffs/``.

    Returns the path on success, ``None`` on failure.  Never raises.
    """
    task_id = (task_id or "").strip()
    if not task_id or not prompt:
        return None

    try:
        root = _repo_root()
        out_dir = root / _HANDOFF_SUBDIR
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = f"cursor-handoff-{task_id}.md"
        path = out_dir / filename
        path.write_text(prompt, encoding="utf-8")

        idx_path = out_dir / "README.md"
        idx_line = f"- [{title or task_id}]({filename})"
        if not idx_path.exists():
            idx_path.write_text(
                "# Cursor implementation handoffs\n\n"
                "Generated prompts for Cursor-driven patching.\n\n"
                + idx_line + "\n",
                encoding="utf-8",
            )
        else:
            existing = idx_path.read_text(encoding="utf-8")
            if idx_line not in existing:
                with idx_path.open("a", encoding="utf-8") as f:
                    if not existing.endswith("\n"):
                        f.write("\n")
                    f.write(idx_line + "\n")

        logger.info("Cursor handoff saved task_id=%s path=%s", task_id, path)
        return path

    except Exception as e:
        logger.warning("save_cursor_handoff failed task_id=%s: %s", task_id, e)
        return None


# ------------------------------------------------------------------
# Convenience: build + save in one call
# ------------------------------------------------------------------


def generate_cursor_handoff(
    prepared_task: dict[str, Any],
    *,
    sections: dict[str, Any] | None = None,
    extra_constraints: str = "",
) -> dict[str, Any]:
    """High-level entry point: build the Cursor handoff prompt and save it.

    Reads sections from ``prepared_task["_openclaw_sections"]`` when
    *sections* is not provided.  Falls back to loading the ``.sections.json``
    sidecar from disk if neither source is available.

    Returns ``{"success": bool, "prompt": str, "path": str | None}``.
    """
    task = (prepared_task or {}).get("task") or {}
    task_id = str(task.get("id") or "").strip()
    title = str(task.get("task") or "").strip() or "Untitled"
    repo_area = (prepared_task or {}).get("repo_area") or {}

    # Resolve sections: parameter → stashed on prepared_task → sidecar on disk
    if sections is None:
        sections = (prepared_task or {}).get("_openclaw_sections") or {}

    if not sections or all(v is None for k, v in sections.items() if k != "_preamble"):
        sections = _load_sections_from_sidecar(task_id)

    prompt = build_cursor_handoff_prompt(
        task_title=title,
        sections=sections,
        task_id=task_id,
        repo_area=repo_area,
        extra_constraints=extra_constraints,
    )

    # Stash on prepared_task for immediate downstream access
    if prepared_task is not None:
        prepared_task["_cursor_handoff_prompt"] = prompt

    path = save_cursor_handoff(task_id, prompt, title=title)

    return {
        "success": bool(path),
        "prompt": prompt,
        "path": str(path) if path else None,
    }


def _load_sections_from_sidecar(task_id: str) -> dict[str, Any]:
    """Best-effort: load sections from the ``.sections.json`` sidecar on disk."""
    if not task_id:
        return {}
    try:
        from app.services._paths import get_writable_bug_investigations_dir
        root = _repo_root()
        search_dirs = [
            get_writable_bug_investigations_dir(),
            root / "docs" / "agents" / "generated-notes",
            root / "docs" / "runbooks" / "triage",
        ]
        for d in search_dirs:
            if not d.is_dir():
                continue
            for pattern in (f"*-{task_id}.sections.json", f"*{task_id}*.sections.json"):
                for f in d.glob(pattern):
                    data = json.loads(f.read_text(encoding="utf-8"))
                    return data.get("sections") or {}
    except Exception as e:
        logger.debug("_load_sections_from_sidecar failed task_id=%s: %s", task_id, e)
    return {}
