"""Alert domain types for Phase 6B."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


@dataclass
class AlertInput:
    """Normalized finding used to generate or deduplicate an alert."""

    alert_type: str
    source: str
    title: str
    summary: str
    severity: AlertSeverity
    investigation_id: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    normalized_finding: str = ""


@dataclass
class AlertRecord:
    """Alert object returned by the engine."""

    alert_id: str
    created_at: str
    severity: str
    source: str
    investigation_id: str | None
    title: str
    summary: str
    evidence: list[dict[str, Any]]
    status: str
    fingerprint: str
    occurrence_count: int = 1
    first_seen: str = ""
    last_seen: str = ""
    updated_at: str = ""
    telegram_sent: bool = False
    deduplicated: bool = False
    snoozed_until: str = ""
