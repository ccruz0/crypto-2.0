"""
Marketing-related settings metadata for Jarvis (secret vs non-secret).

Used by Telegram intake; keep aligned with dashboard / REQUIRED_SETTINGS when present.
"""

from __future__ import annotations

from typing import Any, Literal

SettingMeta = dict[str, Any]

# is_secret=True → secure Telegram path (dashboard | telegram choice).
# is_secret=False → value may be requested directly in the next message.
MARKETING_SETTINGS: dict[str, SettingMeta] = {
    "ga4_booking_event_name": {
        "label": "GA4 booking/conversion event name",
        "is_secret": False,
        "env_var": "JARVIS_GA4_BOOKING_EVENT_NAME",
        "validation": "non_empty",
    },
    "ga4_property_id": {
        "label": "Google Analytics Property ID",
        "is_secret": False,
        "env_var": "JARVIS_GA4_PROPERTY_ID",
        "validation": "numeric",
    },
    "ga4_credentials_json": {
        "label": "GA4 Service Account JSON path",
        "is_secret": False,
        "env_var": "JARVIS_GA4_CREDENTIALS_JSON",
        "validation": "non_empty",
    },
    "google_ads_developer_token": {
        "label": "Google Ads Developer Token",
        "is_secret": True,
        "env_var": "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN",
        "validation": "non_empty",
    },
    "google_ads_customer_id": {
        "label": "Google Ads Customer ID",
        "is_secret": False,
        "env_var": "JARVIS_GOOGLE_ADS_CUSTOMER_ID",
        "validation": "non_empty",
    },
    "search_console_site_url": {
        "label": "Google Search Console Site URL",
        "is_secret": False,
        "env_var": "JARVIS_GSC_SITE_URL",
        "validation": "url",
    },
}


def get_setting_meta(setting_key: str) -> SettingMeta | None:
    return MARKETING_SETTINGS.get((setting_key or "").strip())


def is_secret_setting(setting_key: str) -> bool:
    m = get_setting_meta(setting_key)
    if m is None:
        return True
    return bool(m.get("is_secret", True))
