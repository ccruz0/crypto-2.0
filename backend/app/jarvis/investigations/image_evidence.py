"""Image evidence pipeline: screenshots as read-only investigation evidence.

Introduces the ``image_evidence`` investigation input type. For each uploaded
screenshot we store:
  * image id (artifact id)
  * upload timestamp
  * source (dashboard | telegram | api)
  * optional caption
  * OCR output
  * extracted entities
  * per-image screenshot classification

Images are evidence only. This module never executes image content; it validates
and stores bytes, reads text via OCR, and derives structured evidence items.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.jarvis.artifacts.images import (
    MAX_IMAGES_PER_TASK,
    ImageValidationError,
    create_image_artifact,
)
from app.jarvis.investigations.evidence_model import EvidenceItem
from app.jarvis.investigations.image_classification import (
    ImageInvestigationType,
    classify_image_investigation,
)
from app.jarvis.investigations.ocr import (
    ExtractedEntities,
    extract_entities,
    extract_text_from_image,
    ocr_available,
)

_VALID_SOURCES = frozenset({"dashboard", "telegram", "api", "scheduler", "unknown"})


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


@dataclass
class ImageEvidence:
    """Structured record for a single screenshot used as investigation evidence."""

    image_id: str
    uploaded_at: str
    source: str
    filename: str
    mime_type: str
    caption: str
    ocr_text: str
    entities: ExtractedEntities
    image_investigation_type: ImageInvestigationType
    content_url: str
    file_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "uploaded_at": self.uploaded_at,
            "source": self.source,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "caption": self.caption,
            "ocr_text": self.ocr_text,
            "entities": self.entities.to_dict(),
            "image_investigation_type": self.image_investigation_type.value,
            "content_url": self.content_url,
        }


@dataclass
class ImageEvidenceResult:
    images: list[ImageEvidence] = field(default_factory=list)
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    combined_ocr_text: str = ""
    combined_entities: ExtractedEntities = field(default_factory=ExtractedEntities)
    image_investigation_type: ImageInvestigationType = ImageInvestigationType.UNKNOWN
    ocr_available: bool = False

    def has_images(self) -> bool:
        return bool(self.images)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summarize_entities(entities: ExtractedEntities) -> str:
    parts: list[str] = []
    for label, values in entities.to_dict().items():
        if values:
            parts.append(f"{label}={values[:6]}")
    return "; ".join(parts) if parts else "no structured entities extracted"


def _merge_entities(items: list[ExtractedEntities]) -> ExtractedEntities:
    merged = ExtractedEntities()
    fields = merged.to_dict().keys()
    accumulators: dict[str, list[str]] = {f: [] for f in fields}
    for ent in items:
        for f, values in ent.to_dict().items():
            accumulators[f].extend(values)
    seen_dedupe: dict[str, list[str]] = {}
    for f, values in accumulators.items():
        out: list[str] = []
        seen: set[str] = set()
        for v in values:
            low = v.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(v)
        seen_dedupe[f] = out
    return ExtractedEntities(**seen_dedupe)


def build_image_evidence(
    investigation_id: str,
    attachments: list[dict[str, Any]],
    *,
    source: str = "api",
) -> ImageEvidenceResult:
    """Validate, store, OCR, and classify uploaded screenshots into evidence items."""
    if len(attachments) > MAX_IMAGES_PER_TASK:
        raise ImageValidationError(f"Maximum {MAX_IMAGES_PER_TASK} image attachments allowed")

    norm_source = source if source in _VALID_SOURCES else "unknown"
    result = ImageEvidenceResult(ocr_available=ocr_available())

    per_image_entities: list[ExtractedEntities] = []
    ocr_chunks: list[str] = []

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
            metadata={"context": "investigation_evidence", "caption": caption, "source": norm_source},
        )
        artifact_id = str(record["artifact_id"])
        uploaded_at = str(record.get("created_at") or _now_iso())
        mime_type = record["metadata"]["mime_type"]
        content_url = investigation_content_url(investigation_id, artifact_id)

        ocr_text = extract_text_from_image(data)
        entities = extract_entities(f"{ocr_text}\n{caption}")
        image_type = classify_image_investigation(ocr_text, entities, caption=caption)

        per_image_entities.append(entities)
        if ocr_text:
            ocr_chunks.append(ocr_text)

        image_evidence = ImageEvidence(
            image_id=artifact_id,
            uploaded_at=uploaded_at,
            source=norm_source,
            filename=filename,
            mime_type=mime_type,
            caption=caption,
            ocr_text=ocr_text,
            entities=entities,
            image_investigation_type=image_type,
            content_url=content_url,
            file_path=str(record["path"]),
        )
        result.images.append(image_evidence)

        # 1) Image evidence item (the screenshot itself).
        img_detail = caption or f"User-provided screenshot: {filename}"
        result.evidence_items.append(
            {
                "source": "user",
                "reference": artifact_id,
                "detail": img_detail[:800],
                "confidence": "medium",
                "evidence_type": "image",
                "file_path": str(record["path"]),
                "artifact_id": artifact_id,
                "image_id": artifact_id,
                "uploaded_at": uploaded_at,
                "caption": caption,
                "content_url": content_url,
                "mime_type": mime_type,
                "image_investigation_type": image_type.value,
                "is_direct": False,
            }
        )

        # 2) OCR evidence item (text read from the screenshot).
        ocr_detail = (
            f"OCR text from {filename}: {ocr_text[:600]}"
            if ocr_text
            else f"OCR produced no readable text from {filename}"
            + ("" if result.ocr_available else " (OCR engine unavailable)")
        )
        result.evidence_items.append(
            {
                "source": "ocr",
                "reference": artifact_id,
                "detail": ocr_detail[:800],
                "confidence": "medium" if ocr_text else "low",
                "evidence_type": "ocr",
                "artifact_id": artifact_id,
                "image_id": artifact_id,
                "ocr_text": ocr_text,
                "is_direct": False,
            }
        )

        # 3) Extracted entities evidence item.
        if not entities.is_empty():
            result.evidence_items.append(
                {
                    "source": "ocr",
                    "reference": f"{artifact_id}:entities",
                    "detail": f"Extracted entities from {filename}: {_summarize_entities(entities)}"[:800],
                    "confidence": "medium",
                    "evidence_type": "image_entities",
                    "artifact_id": artifact_id,
                    "image_id": artifact_id,
                    "entities": entities.to_dict(),
                    "image_investigation_type": image_type.value,
                    "is_direct": False,
                }
            )

    result.combined_ocr_text = "\n\n".join(ocr_chunks)[:8000]
    result.combined_entities = _merge_entities(per_image_entities)

    # Overall classification: first decisive per-image type, else classify combined.
    decisive = next(
        (img.image_investigation_type for img in result.images if img.image_investigation_type != ImageInvestigationType.UNKNOWN),
        None,
    )
    if decisive is not None:
        result.image_investigation_type = decisive
    else:
        result.image_investigation_type = classify_image_investigation(
            result.combined_ocr_text, result.combined_entities
        )

    return result
