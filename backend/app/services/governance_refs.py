"""
Shared governance trace helpers: timeline paths/URLs and concise Telegram footers.

Read-only; no new source of truth. See docs/governance/CONTROL_PLANE_TASK_VIEW.md.
"""

from __future__ import annotations

from urllib.parse import quote

from app.services.governance_timeline import notion_page_id_from_governance_task_id


def safe_api_base_url() -> str:
    """API base for links; empty when production env vars are unset (no crash in Telegram)."""
    try:
        from app.core.environment import get_api_base_url

        return (get_api_base_url() or "").rstrip("/")
    except ValueError:
        return ""


def timeline_path_by_governance_task_id(governance_task_id: str) -> str:
    tid = quote((governance_task_id or "").strip(), safe="-_.~")
    return f"/api/governance/tasks/{tid}/timeline"


def timeline_path_by_notion_page_id(page_id: str) -> str:
    pid = quote((page_id or "").strip(), safe="-_.~")
    return f"/api/governance/by-notion/{pid}/timeline"


def timeline_paths_and_urls(
    governance_task_id: str,
    notion_page_id: str | None,
) -> dict[str, str | None]:
    """Relative paths under /api plus optional absolute URLs when base is known."""
    base = safe_api_base_url()
    p_task = timeline_path_by_governance_task_id(governance_task_id)
    nid = (notion_page_id or "").strip() or notion_page_id_from_governance_task_id(governance_task_id)
    p_notion = timeline_path_by_notion_page_id(nid) if nid else None
    return {
        "timeline_by_task_path": p_task,
        "timeline_by_notion_path": p_notion,
        "timeline_by_task_url": f"{base}{p_task}" if base else None,
        "timeline_by_notion_url": f"{base}{p_notion}" if (base and p_notion) else None,
    }


def _timeline_line_html(governance_task_id: str) -> str:
    base = safe_api_base_url()
    tp = timeline_path_by_governance_task_id(governance_task_id)
    if base:
        return f'<i>Timeline</i> <a href="{base}{tp}">open</a>'
    return f"<i>Timeline</i> <code>{tp}</code>"


def append_governance_telegram_trace(
    lines: list[str],
    *,
    governance_task_id: str,
    manifest_id: str | None = None,
) -> None:
    """
    Append a short Notion/mfst line (when applicable) and a timeline line.
    Caller already shows <b>Task</b> with governance_task_id — avoid repeating gov id.
    """
    nid = notion_page_id_from_governance_task_id(governance_task_id)
    bits: list[str] = []
    if nid:
        bits.append(f"<i>Notion</i> <code>{nid}</code>")
    if manifest_id:
        bits.append(f"<i>mfst</i> <code>{manifest_id}</code>")
    lines.append("")
    if bits:
        lines.append(" · ".join(bits))
    lines.append(_timeline_line_html(governance_task_id))


def agent_approval_governance_note_lines(
    *,
    governance_task_id: str,
    notion_page_id: str,
    manifest_id: str,
) -> list[str]:
    """HTML lines injected into prod_mutation agent approval Telegram (enforce path)."""
    return [
        "",
        f"<i>gov</i> <code>{governance_task_id}</code> · <i>Notion</i> <code>{notion_page_id}</code> · <i>mfst</i> <code>{manifest_id}</code>",
        _timeline_line_html(governance_task_id),
        "<i>Approve approves this manifest digest; PROD run uses governance_executor.</i>",
    ]
