"""OCR text extraction and entity parsing for screenshot-driven investigations.

Read-only by design: images are treated as evidence only. This module never
executes image content; it only decodes pixels and reads text out of them.

The OCR engine is pluggable so tests can inject deterministic text without
requiring the tesseract binary. In production it uses Pillow + pytesseract
when both are importable and the tesseract binary is on PATH; otherwise OCR
degrades gracefully to empty text (entity extraction still runs on captions).
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)

# An OCR engine maps raw image bytes to extracted text.
OcrEngine = Callable[[bytes], str]

_MAX_OCR_CHARS = 8000

# Module-level override used by tests to inject deterministic OCR output.
_ENGINE_OVERRIDE: OcrEngine | None = None


def set_ocr_engine(engine: OcrEngine | None) -> None:
    """Install a custom OCR engine (used by tests). Pass None to reset."""
    global _ENGINE_OVERRIDE
    _ENGINE_OVERRIDE = engine


def ocr_available() -> bool:
    """Return True when a real OCR backend (Pillow + pytesseract + binary) is usable."""
    if _ENGINE_OVERRIDE is not None:
        return True
    try:
        import PIL  # noqa: F401
        import pytesseract  # noqa: F401
    except Exception:
        return False
    return shutil.which("tesseract") is not None


def _tesseract_engine(data: bytes) -> str:
    import io

    from PIL import Image  # type: ignore
    import pytesseract  # type: ignore

    with Image.open(io.BytesIO(data)) as img:
        # Convert to a mode tesseract handles well; never executes image data.
        prepared = img.convert("L")
        return pytesseract.image_to_string(prepared)


def extract_text_from_image(data: bytes) -> str:
    """Extract text from raw image bytes. Returns '' on any failure (degrades safely)."""
    if not data:
        return ""
    engine = _ENGINE_OVERRIDE
    if engine is None:
        if not ocr_available():
            logger.info("ocr.unavailable: tesseract/Pillow not installed; returning empty OCR text")
            return ""
        engine = _tesseract_engine
    try:
        text = engine(data) or ""
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("ocr.extract_failed err=%s", exc)
        return ""
    return _normalize_ocr_text(text)


def _normalize_ocr_text(text: str) -> str:
    cleaned = (text or "").replace("\x00", " ")
    # Collapse runs of blank lines while preserving line structure for entities.
    lines = [ln.rstrip() for ln in cleaned.splitlines()]
    collapsed: list[str] = []
    blank = 0
    for ln in lines:
        if ln.strip():
            blank = 0
            collapsed.append(ln)
        else:
            blank += 1
            if blank <= 1:
                collapsed.append("")
    result = "\n".join(collapsed).strip()
    return result[:_MAX_OCR_CHARS]


# --- Entity extraction -------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)

_TIMESTAMP_RES = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"),
    re.compile(r"\b\d{2}:\d{2}:\d{2}\b"),
    re.compile(r"\b\d{4}/\d{2}/\d{2}\b"),
]

# Numeric exchange/HTTP-style error codes (3-6 digits) and symbolic error codes.
_NUMERIC_ERROR_RE = re.compile(r"\b(?:error[_\s]?code|code|err|status)[\s:=#]*([0-9]{3,6})\b", re.IGNORECASE)
_BARE_KNOWN_ERROR_RE = re.compile(r"\b(40101|50001|401|403|404|429|500|502|503|504)\b")
_SYMBOLIC_ERROR_RE = re.compile(r"\b(?:ERR|E)_[A-Z0-9_]{2,40}\b")
_HTTP_STATUS_WORD_RE = re.compile(r"\bHTTP[\s/]?(\d{3})\b", re.IGNORECASE)

# Git commit hashes: 7-40 hex chars (word-bounded), avoid pure decimal sequences.
_COMMIT_RE = re.compile(r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b", re.IGNORECASE)

# GitHub Actions run ids: "run #123456789", "runs/123456789", "run id 123456789".
_GH_RUN_RE = re.compile(
    r"(?:actions?/runs?/|run[\s#:]*(?:id[\s:#]*)?|workflow\s+run[\s#:]*)(\d{6,})",
    re.IGNORECASE,
)

# Exchange order ids: explicit "order id" context, long numeric ids, or UUIDs.
_ORDER_ID_CTX_RE = re.compile(
    r"order[\s_]*(?:id|#|number)?[\s:#=]*([0-9]{6,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)

# Container / pod names: hint words followed by a docker-style identifier.
_CONTAINER_RE = re.compile(
    r"(?:container|pod|service|deployment)[\s:=]+[\"']?([a-z0-9][a-z0-9_.-]{2,60})",
    re.IGNORECASE,
)
# Docker-compose style names embedded in logs e.g. crypto-2.0-backend-1.
_COMPOSE_NAME_RE = re.compile(r"\b([a-z0-9]+(?:[._-][a-z0-9]+){1,5}-\d+)\b", re.IGNORECASE)

# Service names (project-style): word containing backend/frontend/worker/api/db etc.
_SERVICE_HINT_RE = re.compile(
    r"\b([a-z0-9-]*(?:backend|frontend|worker|api|gateway|scheduler|poller|updater|db|database|redis|nginx|market-updater)[a-z0-9-]*)\b",
    re.IGNORECASE,
)

# Prometheus/Grafana alert names: PascalCase identifiers (>=2 words).
_ALERT_NAME_RE = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+){1,6})\b")
# Alertname=Foo or "alert: Foo".
_ALERT_CTX_RE = re.compile(r"(?:alert[name]*|alertname)[\s:=]+[\"']?([A-Za-z][A-Za-z0-9_]{2,60})", re.IGNORECASE)

_ALERT_SUFFIXES = (
    "High",
    "Low",
    "Down",
    "Error",
    "Errors",
    "Failing",
    "Failed",
    "Restarts",
    "Restarting",
    "Unavailable",
    "Latency",
    "Saturation",
    "Pending",
    "Firing",
    "Critical",
    "Warning",
    "Usage",
    "Lag",
)

_KNOWN_SERVICE_NOISE = frozenset(
    {"the", "and", "for", "with", "this", "that", "from", "your"}
)


def _dedupe(seq: list[str], *, limit: int = 25) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        key = item.strip()
        if not key:
            continue
        low = key.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(key)
        if len(out) >= limit:
            break
    return out


@dataclass
class ExtractedEntities:
    error_codes: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    timestamps: list[str] = field(default_factory=list)
    container_names: list[str] = field(default_factory=list)
    service_names: list[str] = field(default_factory=list)
    alert_names: list[str] = field(default_factory=list)
    commit_hashes: list[str] = field(default_factory=list)
    github_run_ids: list[str] = field(default_factory=list)
    order_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "error_codes": self.error_codes,
            "urls": self.urls,
            "timestamps": self.timestamps,
            "container_names": self.container_names,
            "service_names": self.service_names,
            "alert_names": self.alert_names,
            "commit_hashes": self.commit_hashes,
            "github_run_ids": self.github_run_ids,
            "order_ids": self.order_ids,
        }

    def is_empty(self) -> bool:
        return not any(self.to_dict().values())

    def total(self) -> int:
        return sum(len(v) for v in self.to_dict().values())


def _looks_like_alert_name(token: str) -> bool:
    if any(token.endswith(suffix) for suffix in _ALERT_SUFFIXES):
        return True
    return False


def extract_entities(text: str) -> ExtractedEntities:
    """Extract structured entities from OCR/caption text (deterministic, regex-based)."""
    blob = text or ""

    urls = _dedupe(_URL_RE.findall(blob))

    timestamps: list[str] = []
    for rx in _TIMESTAMP_RES:
        timestamps.extend(rx.findall(blob))
    timestamps = _dedupe(timestamps)

    error_codes: list[str] = []
    error_codes.extend(_NUMERIC_ERROR_RE.findall(blob))
    error_codes.extend(_BARE_KNOWN_ERROR_RE.findall(blob))
    error_codes.extend(_HTTP_STATUS_WORD_RE.findall(blob))
    error_codes.extend(m.group(0) for m in _SYMBOLIC_ERROR_RE.finditer(blob))
    error_codes = _dedupe(error_codes)

    github_run_ids = _dedupe(_GH_RUN_RE.findall(blob))

    order_ids: list[str] = list(_ORDER_ID_CTX_RE.findall(blob))
    order_ids.extend(_UUID_RE.findall(blob))
    order_ids = _dedupe(order_ids)
    run_id_set = set(github_run_ids)
    order_ids = [oid for oid in order_ids if oid not in run_id_set]

    # Commit hashes: exclude pure-numeric (those are codes/ids) and known run/order ids.
    commit_hashes = []
    for h in _COMMIT_RE.findall(blob):
        if h.lower() in {o.lower() for o in order_ids}:
            continue
        commit_hashes.append(h)
    commit_hashes = _dedupe(commit_hashes)

    container_names = list(_CONTAINER_RE.findall(blob))
    container_names.extend(_COMPOSE_NAME_RE.findall(blob))
    container_names = _dedupe(container_names)

    service_names = [
        s
        for s in _SERVICE_HINT_RE.findall(blob)
        if s.lower() not in _KNOWN_SERVICE_NOISE
    ]
    service_names = _dedupe(service_names)

    alert_names: list[str] = list(_ALERT_CTX_RE.findall(blob))
    for token in _ALERT_NAME_RE.findall(blob):
        if _looks_like_alert_name(token):
            alert_names.append(token)
    alert_names = _dedupe(alert_names)

    return ExtractedEntities(
        error_codes=error_codes,
        urls=urls,
        timestamps=timestamps,
        container_names=container_names,
        service_names=service_names,
        alert_names=alert_names,
        commit_hashes=commit_hashes,
        github_run_ids=github_run_ids,
        order_ids=order_ids,
    )
