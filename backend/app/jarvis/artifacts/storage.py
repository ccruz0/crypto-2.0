"""Artifact storage for Jarvis task execution."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

ArtifactFormat = Literal["markdown", "json", "text", "report"]

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ARTIFACTS_DIR = _REPO_ROOT / "backend" / "app" / "jarvis" / "artifacts" / "data"


def _ensure_dir() -> Path:
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return _ARTIFACTS_DIR


def _serialize_content(content: Any, fmt: ArtifactFormat) -> str:
    if fmt == "json":
        return json.dumps(content, indent=2, default=str)
    if isinstance(content, str):
        return content
    return json.dumps(content, indent=2, default=str)


def create_artifact(
    *,
    task_id: str,
    name: str,
    content: Any,
    fmt: ArtifactFormat = "text",
    step_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an artifact file and return its metadata envelope."""
    artifact_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    body = _serialize_content(content, fmt)
    ext = {"markdown": "md", "json": "json", "text": "txt", "report": "md"}.get(fmt, "txt")
    rel_path = f"{task_id}/{artifact_id}.{ext}"
    target = _ensure_dir() / task_id
    target.mkdir(parents=True, exist_ok=True)
    file_path = target / f"{artifact_id}.{ext}"
    file_path.write_text(body, encoding="utf-8")
    try:
        rel_path = str(file_path.relative_to(_REPO_ROOT))
    except ValueError:
        rel_path = str(file_path)
    record = {
        "artifact_id": artifact_id,
        "task_id": task_id,
        "name": name,
        "format": fmt,
        "step_id": step_id,
        "path": rel_path,
        "size_bytes": file_path.stat().st_size,
        "created_at": ts,
        "metadata": metadata or {},
        "preview": body[:500],
    }
    return record


def load_artifact_content(record: dict[str, Any]) -> str:
    rel = record.get("path")
    if not rel:
        return ""
    path = _REPO_ROOT / str(rel)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")
