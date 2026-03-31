"""Normalize raw Notion task dicts for routing, queue isolation, and artifacts."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def normalize_task(raw_task: dict[str, Any]) -> dict[str, Any]:
    """
    Derive structured fields from a Notion-style task dict (keys: task, details, type, ...).

    task_type: docs_investigation | code_change | anomaly | infra | unknown
    """
    title = str((raw_task or {}).get("task") or "").strip()
    details = str((raw_task or {}).get("details") or "").strip()
    notion_type = str((raw_task or {}).get("type") or "").strip().lower()
    combined = f"{title}\n{details}".lower()

    task_type = "unknown"
    if "anomaly" in combined:
        task_type = "anomaly"
    elif any(w in combined for w in ("documentation", "document ", " docs", "doc ", "doc.", "check ", "verify ", " review")) or any(
        w in title.lower() for w in ("doc", "check", "verify")
    ):
        task_type = "docs_investigation"
    elif any(w in combined for w in ("deploy", "docker", "nginx", "infrastructure", " infra", "aws ec2")):
        task_type = "infra"
    elif any(w in combined for w in ("fix", "error", "bug", "exception", "stack trace")):
        task_type = "code_change"
    elif notion_type in ("bug", "bugfix", "investigation"):
        task_type = "code_change"

    risk_level = "medium"
    if re.search(r"do\s+not\s+modify\s+code", combined) or "no code change" in combined:
        risk_level = "low"
    elif any(w in combined for w in ("production", "live trading", "real money", "exchange order")):
        risk_level = "high"

    constraints: list[str] = []
    for m in re.finditer(r"(do not|don't|never)\s+([^\n.]{3,120})", combined, re.I):
        constraints.append(m.group(0).strip()[:200])
    for m in re.finditer(r"\bno\s+([a-z][^\n,.]{2,80})", combined, re.I):
        constraints.append(m.group(0).strip()[:200])
    for m in re.finditer(r"\bonly\s+([^\n.]{3,120})", combined, re.I):
        constraints.append(m.group(0).strip()[:200])
    # de-dup preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for c in constraints:
        if c.lower() not in seen:
            seen.add(c.lower())
            uniq.append(c)
    constraints = uniq[:12]

    needs_clarification = (len(title) + len(details)) < 25 or (
        task_type == "unknown" and len(details.strip()) < 10
    )

    objective = title if title else (details[:200] if details else "Untitled task")
    scope: list[str] = []
    if notion_type:
        scope.append(f"notion_type:{notion_type}")
    if details:
        scope.append("details_present")

    success_criteria: list[str] = [
        "Structured investigation or doc output saved to writable artifact path",
        "Task lifecycle updated appropriately in Notion",
    ]
    if task_type == "docs_investigation":
        success_criteria.insert(0, "Documentation accuracy confirmed with file references")

    out = {
        "title": title or objective,
        "objective": objective,
        "scope": scope,
        "constraints": constraints,
        "task_type": task_type,
        "risk_level": risk_level,
        "needs_clarification": needs_clarification,
        "success_criteria": success_criteria,
    }
    logger.debug(
        "task_normalizer: type=%s risk=%s title_preview=%r",
        task_type,
        risk_level,
        (title[:60] + "…") if len(title) > 60 else title,
    )
    return out


def partition_tasks_queue_isolation(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Human-intent tasks first, anomaly-classified tasks last (same relative order within each bucket).
    """
    human_tasks: list[dict[str, Any]] = []
    anomaly_tasks: list[dict[str, Any]] = []
    for t in tasks:
        if normalize_task(t).get("task_type") == "anomaly":
            anomaly_tasks.append(t)
        else:
            human_tasks.append(t)
    return human_tasks + anomaly_tasks


def save_normalized_task_artifact(task_id: str, normalized: dict[str, Any]) -> str | None:
    """
    Write ``task-{task_id}.normalized.json`` under writable tasks dir.
    Returns path string on success, None on failure.
    """
    tid = (task_id or "").strip()
    if not tid:
        return None
    try:
        from app.services.artifact_paths import get_normalized_tasks_dir
        from app.services import path_guard

        out_dir = get_normalized_tasks_dir()
        path = out_dir / f"task-{tid}.normalized.json"
        payload = json.dumps(normalized, indent=2, ensure_ascii=False) + "\n"
        path_guard.safe_write_text(path, payload, context="task_normalizer:normalized_json")
        logger.info("artifact_written path=%s task_id=%s", path, tid[:12])
        return str(path)
    except Exception as e:
        logger.warning("artifact_written failed task_id=%s err=%s", tid[:12], e)
        return None
