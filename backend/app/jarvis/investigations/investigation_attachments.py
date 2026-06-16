"""User-supplied image attachments for investigations (evidence/context only)."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any

from app.jarvis.artifacts import storage as artifact_storage
from app.jarvis.artifacts.images import (
    MAX_IMAGES_PER_TASK,
    ImageValidationError,
    create_image_artifact,
)
from app.jarvis.investigations.evidence_model import EvidenceItem


def investigation_content_url(investigation_id: str, artifact_id: str) -> str:
    return f"/api/jarvis/investigations/{investigation_id}/attachments/{artifact_id}/content"


def decode_attachment_payload(content_base64: str) -> bytes:
    """Decode base64 image payload. Binary is validated as image only; never executed."""
    raw = (content_base64 or "").strip()
    if raw.startswith("data:"):
        comma = raw.find(",")
        if comma == -1:
            raise ImageValidationError("Invalid data URL")
        raw = raw[comma + 1 :]
    try:
        return base64.b64decode(raw, validate=True)
    except binascii.Error as exc:
        raise ImageValidationError("Invalid base64 encoding") from exc


def attachments_to_evidence(
    investigation_id: str,
    attachments: list[dict[str, Any]],
) -> list[EvidenceItem]:
    """Validate, store, and convert image attachments into read-only evidence items."""
    if len(attachments) > MAX_IMAGES_PER_TASK:
        raise ImageValidationError(f"Maximum {MAX_IMAGES_PER_TASK} image attachments allowed")

    evidence: list[EvidenceItem] = []
    for att in attachments:
        filename = str(att.get("filename") or "attachment")
        content_type = att.get("content_type")
        caption = str(att.get("caption") or "").strip()
        data = decode_attachment_payload(str(att.get("content_base64") or ""))

        record = create_image_artifact(
            task_id=investigation_id,
            filename=filename,
            data=data,
            content_type=content_type,
            metadata={"context": "investigation_evidence", "caption": caption},
        )
        artifact_id = str(record["artifact_id"])
        detail = caption or f"User-provided screenshot: {filename}"
        evidence.append(
            {
                "source": "user",
                "reference": artifact_id,
                "detail": detail[:800],
                "confidence": "medium",
                "evidence_type": "image",
                "file_path": record["path"],
                "artifact_id": artifact_id,
                "content_url": investigation_content_url(investigation_id, artifact_id),
                "mime_type": record["metadata"]["mime_type"],
                "is_direct": False,
            }
        )
    return evidence


def resolve_investigation_attachment_file(investigation_id: str, artifact_id: str) -> Path | None:
    """Resolve stored investigation attachment path from artifact id."""
    task_dir = artifact_storage._ensure_dir() / investigation_id
    if not task_dir.is_dir():
        return None
    for candidate in task_dir.glob(f"{artifact_id}.*"):
        if candidate.is_file():
            root = artifact_storage._ARTIFACTS_DIR.parent
            if str(candidate.resolve()).startswith(str(root.resolve())):
                return candidate
    return None
