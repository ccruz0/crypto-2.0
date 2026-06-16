"""Image attachment validation and storage for Jarvis task artifacts."""

from __future__ import annotations

import imghdr
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.jarvis.artifacts import storage as artifact_storage

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES_PER_TASK = 5

_ALLOWED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_ALLOWED_MIME = frozenset({"image/png", "image/jpeg", "image/webp"})
_EXT_FOR_MIME = {
    "png": ".png",
    "jpeg": ".jpg",
    "webp": ".webp",
}


class ImageValidationError(ValueError):
    """Raised when an uploaded image fails validation."""


def _detect_image_type(data: bytes) -> str | None:
    kind = imghdr.what(None, h=data[:512])
    if kind == "jpeg":
        return "jpeg"
    if kind in {"png", "webp"}:
        return kind
    return None


def validate_image_upload(
    *,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> tuple[str, str]:
    """Validate image bytes and return (mime_type, extension)."""
    if not data:
        raise ImageValidationError("Empty image upload")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageValidationError(f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit")

    ext = Path(filename or "").suffix.lower()
    if ext and ext not in _ALLOWED_EXTENSIONS:
        raise ImageValidationError(f"Unsupported file type: {ext}")

    detected = _detect_image_type(data)
    if not detected:
        raise ImageValidationError("File is not a valid PNG, JPG/JPEG, or WEBP image")

    mime = "image/jpeg" if detected == "jpeg" else f"image/{detected}"
    if content_type and content_type.split(";")[0].strip().lower() not in _ALLOWED_MIME:
        raise ImageValidationError(f"Unsupported content type: {content_type}")

    resolved_ext = _EXT_FOR_MIME.get(detected, ext or ".png")
    return mime, resolved_ext


def create_image_artifact(
    *,
    task_id: str,
    filename: str,
    data: bytes,
    content_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a binary image artifact and return metadata envelope."""
    mime, ext = validate_image_upload(filename=filename, content_type=content_type, data=data)
    artifact_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    target = artifact_storage._ensure_dir() / task_id
    target.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or "attachment").stem[:80] or "attachment"
    file_name = f"{artifact_id}{ext}"
    file_path = target / file_name
    file_path.write_bytes(data)
    try:
        rel_path = str(file_path.relative_to(artifact_storage._ARTIFACTS_DIR.parent))
    except ValueError:
        rel_path = str(file_path)

    record = {
        "artifact_id": artifact_id,
        "task_id": task_id,
        "name": safe_name,
        "format": "image",
        "step_id": None,
        "path": rel_path,
        "size_bytes": file_path.stat().st_size,
        "created_at": ts,
        "metadata": {
            **(metadata or {}),
            "mime_type": mime,
            "original_filename": filename,
            "content_type": mime,
        },
        "preview": f"[image {mime} {len(data)} bytes]",
        "content_url": f"/api/jarvis/tasks/execution/{task_id}/artifacts/{artifact_id}/content",
    }
    return record


def resolve_artifact_file(task_id: str, artifact_id: str, artifacts: list[dict[str, Any]]) -> Path | None:
    """Resolve artifact file path from task artifact records."""
    for record in artifacts:
        if record.get("artifact_id") != artifact_id:
            continue
        rel = record.get("path")
        if not rel:
            return None
        path = Path(str(rel))
        if not path.is_absolute():
            path = artifact_storage._ARTIFACTS_DIR.parent / path
        if path.is_file() and str(path).startswith(str(artifact_storage._ARTIFACTS_DIR.parent)):
            return path
    # Fallback: scan task directory
    task_dir = artifact_storage._ensure_dir() / task_id
    if not task_dir.is_dir():
        return None
    for candidate in task_dir.glob(f"{artifact_id}.*"):
        if candidate.is_file():
            return candidate
    return None
