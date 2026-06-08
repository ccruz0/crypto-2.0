"""Service helpers to consume Google integrations readiness for Jarvis."""

from __future__ import annotations

from typing import Any, Optional


def _unavailable_readiness_payload() -> dict[str, Any]:
    return {
        "success": False,
        "overall_status": "unavailable",
        "next_action": None,
        "items": [],
    }


def _load_google_readiness_helpers() -> tuple[Any, Any] | None:
    try:
        from app.api.routes_admin import (
            _build_google_readiness_message,
            get_google_integrations_readiness_payload,
        )

        return get_google_integrations_readiness_payload, _build_google_readiness_message
    except (ImportError, AttributeError):
        return None


def get_google_integrations_readiness_for_jarvis() -> dict[str, Any]:
    """
    Return backend-friendly readiness payload for assistant/tool guard checks.

    This reuses existing API readiness composition logic without duplicating validators.
    """
    helpers = _load_google_readiness_helpers()
    payload = helpers[0]() if helpers else _unavailable_readiness_payload()
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
    helpers = _load_google_readiness_helpers()
    if helpers is None:
        return "Google integrations readiness could not be determined."
    get_payload, build_message = helpers
    payload = get_payload()
    return build_message(payload)

