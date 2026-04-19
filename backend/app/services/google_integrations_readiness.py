"""Service helpers to consume Google integrations readiness for Jarvis."""

from __future__ import annotations

from typing import Any, Optional

from app.api.routes_admin import (
    get_google_integrations_readiness_payload,
    _build_google_readiness_message,
)


def get_google_integrations_readiness_for_jarvis() -> dict[str, Any]:
    """
    Return backend-friendly readiness payload for assistant/tool guard checks.

    This reuses existing API readiness composition logic without duplicating validators.
    """
    payload = get_google_integrations_readiness_payload()
    return {
        "overall_status": payload.get("overall_status"),
        "next_action": payload.get("next_action"),
        "items": payload.get("items") or [],
    }


def get_google_integration_readiness_item_for_jarvis(integration: str) -> Optional[dict[str, Any]]:
    for item in get_google_integrations_readiness_for_jarvis().get("items", []):
        if isinstance(item, dict) and str(item.get("integration") or "").strip() == integration:
            return item
    return None


def get_google_integrations_readiness_message_for_jarvis() -> str:
    payload = get_google_integrations_readiness_payload()
    return _build_google_readiness_message(payload)

