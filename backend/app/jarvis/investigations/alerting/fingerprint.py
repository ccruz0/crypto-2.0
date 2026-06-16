"""Alert fingerprinting and deduplication helpers."""

from __future__ import annotations

import hashlib
import re

from app.jarvis.investigations.alerting.types import AlertInput


def normalize_finding_text(text: str) -> str:
    """Collapse whitespace and strip volatile tokens for stable fingerprints."""
    cleaned = (text or "").lower().strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Remove timestamps and UUIDs that would break deduplication.
    cleaned = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "", cleaned)
    cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}\b", "", cleaned)
    return cleaned.strip()


def build_fingerprint(alert_input: AlertInput) -> str:
    """
    Fingerprint from alert type, source, and normalized finding.

    Duplicate alerts with the same fingerprint collapse into one open alert.
    """
    normalized = alert_input.normalized_finding or normalize_finding_text(alert_input.summary)
    normalized = normalize_finding_text(normalized)
    payload = f"{alert_input.alert_type}|{alert_input.source}|{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
