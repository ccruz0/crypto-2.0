"""Builder artifact persistence and retrieval for Jarvis Control Center."""

from __future__ import annotations

import json
from typing import Any

from app.jarvis.control import persistence as jcp


class BuilderArtifactError(ValueError):
    """Raised when artifact payload is invalid."""


class BuilderArtifactNotFoundError(LookupError):
    """Raised when the target builder task does not exist."""


def _ensure_json_serializable(value: Any) -> None:
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise BuilderArtifactError("artifact must be JSON-serializable") from exc


def _artifact_response(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task["task_id"],
        "artifact": task.get("builder_artifact") if isinstance(task.get("builder_artifact"), dict) else {},
        "updated_at": task.get("artifact_updated_at"),
        "version": int(task.get("artifact_version") or 0),
    }


def get_builder_artifact(task_id: str) -> dict[str, Any] | None:
    """Return artifact envelope for a builder task, or None if not found."""
    task = jcp.get_control_task(task_id)
    if task is None or task.get("mode") != "builder":
        return None
    return _artifact_response(task)


def save_builder_artifact(task_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
    """Replace the stored builder artifact and bump version."""
    if not isinstance(artifact, dict):
        raise BuilderArtifactError("artifact must be a JSON object")
    _ensure_json_serializable(artifact)
    updated = jcp.persist_builder_artifact(task_id, artifact, merge=False)
    if updated is None:
        raise BuilderArtifactNotFoundError(f"Builder task not found: {task_id}")
    return _artifact_response(updated)


def update_builder_artifact(task_id: str, partial_update: dict[str, Any]) -> dict[str, Any]:
    """Merge partial fields into the stored builder artifact and bump version."""
    if not isinstance(partial_update, dict):
        raise BuilderArtifactError("partial_update must be a JSON object")
    _ensure_json_serializable(partial_update)
    updated = jcp.persist_builder_artifact(task_id, partial_update, merge=True)
    if updated is None:
        raise BuilderArtifactNotFoundError(f"Builder task not found: {task_id}")
    return _artifact_response(updated)
