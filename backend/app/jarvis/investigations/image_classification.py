"""Screenshot classification and image-aware investigation routing.

Given OCR text + extracted entities from a screenshot, classify the screenshot
into an ``image_investigation_type`` and route the investigation to the correct
objective-aware investigation type. Images influence routing decisions here:
the routed type combines the user objective, image classification, and OCR
evidence.
"""

from __future__ import annotations

import re
from enum import Enum

from app.jarvis.investigations.objective_classification import (
    InvestigationObjectiveType,
    classify_investigation_objective,
)
from app.jarvis.investigations.ocr import ExtractedEntities


class ImageInvestigationType(str, Enum):
    DEPLOYMENT_FAILURE = "deployment_failure"
    ALERT_INVESTIGATION = "alert_investigation"
    EXCHANGE_ERROR = "exchange_error"
    DASHBOARD_ERROR = "dashboard_error"
    ORDER_RECONCILIATION = "order_reconciliation"
    SYSTEM_HEALTH = "system_health"
    GITHUB_ACTIONS_FAILURE = "github_actions_failure"
    UNKNOWN = "unknown"


_GITHUB_RE = re.compile(
    r"github\s+actions?|workflow\s+run|actions?/runs?/|\.github/workflows|"
    r"run\s+failed|ci\s+(?:failed|failing)|build\s+failed",
    re.IGNORECASE,
)
_DEPLOY_RE = re.compile(
    r"deploy(?:ment|ed|ing)?|crashloopbackoff|imagepullbackoff|container\s+(?:exited|restart|failed)|"
    r"docker|compose|unhealthy|exited\s*\(\d+\)|oomkilled|failed\s+to\s+start|rollout",
    re.IGNORECASE,
)
_ALERT_RE = re.compile(
    r"\balert(?:manager|s)?\b|firing|prometheus|grafana|pending\s+alert|"
    r"severity\s*[:=]\s*(?:critical|warning|high)|\[firing\]",
    re.IGNORECASE,
)
_EXCHANGE_RE = re.compile(
    r"crypto\.?com|exchange|binance|40101|invalid_api_key|invalid\s+api\s+key|"
    r"authentication\s+fail|auth\s+error|signature|api[_\s-]?key|unauthorized",
    re.IGNORECASE,
)
_ORDER_RE = re.compile(
    r"open\s+orders?|order\s+mismatch|reconcil|filled\s+order|trigger\s+order|"
    r"orders?\s+(?:missing|not\s+match)",
    re.IGNORECASE,
)
_DASHBOARD_RE = re.compile(
    r"dashboard|mismatch|portfolio|equity|balance|stale|jarvis",
    re.IGNORECASE,
)
_SYSTEM_HEALTH_RE = re.compile(
    r"health\s*check|degraded|cpu\s+usage|memory\s+usage|disk\s+usage|"
    r"latency|503\s+service|service\s+unavailable|uptime",
    re.IGNORECASE,
)

_AUTH_SIGNAL_RE = re.compile(
    r"40101|401\b|unauthorized|invalid[_\s]?api[_\s]?key|authentication\s+fail|"
    r"signature|auth\s+error|api\s+credential",
    re.IGNORECASE,
)


def classify_image_investigation(
    ocr_text: str,
    entities: ExtractedEntities | None = None,
    *,
    caption: str = "",
) -> ImageInvestigationType:
    """Classify a screenshot from its OCR text + entities (deterministic, first match wins)."""
    entities = entities or ExtractedEntities()
    blob = f"{ocr_text or ''}\n{caption or ''}"

    has_alert_name = bool(entities.alert_names)
    has_github_run = bool(entities.github_run_ids)
    has_exchange_code = any(c in {"40101", "401"} for c in entities.error_codes)

    # GitHub Actions failures take priority when explicit CI signals are present.
    if _GITHUB_RE.search(blob) or has_github_run:
        return ImageInvestigationType.GITHUB_ACTIONS_FAILURE

    # Prometheus/Grafana alerts: keyword OR a detected PascalCase alert name.
    if _ALERT_RE.search(blob) or has_alert_name:
        return ImageInvestigationType.ALERT_INVESTIGATION

    # Exchange/auth errors (Crypto.com 40101 etc.).
    if has_exchange_code or _EXCHANGE_RE.search(blob):
        if _ORDER_RE.search(blob) and not _AUTH_SIGNAL_RE.search(blob):
            return ImageInvestigationType.ORDER_RECONCILIATION
        return ImageInvestigationType.EXCHANGE_ERROR

    if _ORDER_RE.search(blob):
        return ImageInvestigationType.ORDER_RECONCILIATION

    if _DEPLOY_RE.search(blob):
        return ImageInvestigationType.DEPLOYMENT_FAILURE

    if _SYSTEM_HEALTH_RE.search(blob):
        return ImageInvestigationType.SYSTEM_HEALTH

    if _DASHBOARD_RE.search(blob):
        return ImageInvestigationType.DASHBOARD_ERROR

    return ImageInvestigationType.UNKNOWN


# Map screenshot classification -> objective-aware investigation type.
_IMAGE_TYPE_TO_OBJECTIVE: dict[ImageInvestigationType, InvestigationObjectiveType] = {
    ImageInvestigationType.DEPLOYMENT_FAILURE: InvestigationObjectiveType.DEPLOYMENT_HEALTH,
    ImageInvestigationType.GITHUB_ACTIONS_FAILURE: InvestigationObjectiveType.DEPLOYMENT_HEALTH,
    ImageInvestigationType.ALERT_INVESTIGATION: InvestigationObjectiveType.ALERT_INVESTIGATION,
    ImageInvestigationType.EXCHANGE_ERROR: InvestigationObjectiveType.EXCHANGE_AUTH_INVESTIGATION,
    ImageInvestigationType.ORDER_RECONCILIATION: InvestigationObjectiveType.ORDER_RECONCILIATION,
    ImageInvestigationType.DASHBOARD_ERROR: InvestigationObjectiveType.ORDER_RECONCILIATION,
    ImageInvestigationType.SYSTEM_HEALTH: InvestigationObjectiveType.DEPLOYMENT_HEALTH,
    ImageInvestigationType.UNKNOWN: InvestigationObjectiveType.GENERIC_INVESTIGATION,
}

# Keyword hints injected into the effective objective so downstream Phase 4A
# collector selection (investigation_types.py) and the planner both route on
# the image-derived signal.
_OBJECTIVE_HINTS: dict[InvestigationObjectiveType, str] = {
    InvestigationObjectiveType.DEPLOYMENT_HEALTH: "deployment health container docker service unhealthy",
    InvestigationObjectiveType.ALERT_INVESTIGATION: "alert investigation prometheus alert firing",
    InvestigationObjectiveType.EXCHANGE_AUTH_INVESTIGATION: "crypto.com exchange auth authentication 40101 api credential",
    InvestigationObjectiveType.ORDER_RECONCILIATION: "open orders reconciliation dashboard exchange mismatch",
    InvestigationObjectiveType.SIGNAL_MONITOR_INVESTIGATION: "signal monitor",
    InvestigationObjectiveType.REPOSITORY_ANALYSIS: "repository analysis",
    InvestigationObjectiveType.GENERIC_INVESTIGATION: "",
}


def objective_type_for_image(image_type: ImageInvestigationType) -> InvestigationObjectiveType:
    return _IMAGE_TYPE_TO_OBJECTIVE.get(image_type, InvestigationObjectiveType.GENERIC_INVESTIGATION)


def route_image_investigation(
    *,
    objective: str,
    image_type: ImageInvestigationType,
    ocr_text: str = "",
    entities: ExtractedEntities | None = None,
) -> InvestigationObjectiveType:
    """Determine the investigation type from objective + image classification + OCR evidence.

    Precedence:
      1. A specific (non-generic) classification from the user objective text wins
         when the user was explicit about what to investigate.
      2. Otherwise the screenshot classification drives routing.
      3. OCR text is appended so the objective classifier can pick up codes/keywords
         that only appear in the image (e.g. 40101, alert names).
    """
    objective_text = (objective or "").strip()
    objective_type = classify_investigation_objective(objective_text)

    image_objective_type = objective_type_for_image(image_type)

    if objective_type != InvestigationObjectiveType.GENERIC_INVESTIGATION:
        # User was explicit; honor their objective.
        return objective_type

    if image_objective_type != InvestigationObjectiveType.GENERIC_INVESTIGATION:
        return image_objective_type

    # Fall back to classifying objective + OCR text together.
    combined = f"{objective_text}\n{ocr_text or ''}"
    return classify_investigation_objective(combined)


def build_effective_objective(
    *,
    objective: str,
    routed_type: InvestigationObjectiveType,
    ocr_text: str = "",
    entities: ExtractedEntities | None = None,
) -> str:
    """Compose an effective objective string that carries image-derived routing hints.

    The original objective is preserved verbatim at the front so user intent is
    never lost; image-derived hints + salient OCR signals are appended so the
    Phase 4A collector selector gathers real domain evidence.
    """
    parts: list[str] = []
    base = (objective or "").strip()
    if base:
        parts.append(base)

    hint = _OBJECTIVE_HINTS.get(routed_type, "")
    if hint:
        parts.append(hint)

    entities = entities or ExtractedEntities()
    salient: list[str] = []
    salient.extend(entities.error_codes[:5])
    salient.extend(entities.alert_names[:3])
    salient.extend(entities.container_names[:3])
    salient.extend(entities.service_names[:3])
    if salient:
        parts.append("screenshot signals: " + " ".join(salient))

    return "  ".join(parts).strip() or base
