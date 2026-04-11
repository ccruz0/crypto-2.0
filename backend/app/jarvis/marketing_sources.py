"""
Read-only marketing data adapters for Peluquería Cruz (Jarvis Marketing Intelligence).

Configuration is driven by environment variables (no hardcoded secrets).
When credentials or mappings are missing, callers receive structured ``unavailable`` payloads.

Live Google API calls are not wired in this patch; set ``JARVIS_MARKETING_LIVE_APIS=true`` only
when real adapters are implemented (still read-only).
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

# --- Environment variable names (document for operators) ---

ENV_GSC_SITE = "JARVIS_GSC_SITE_URL"
ENV_GSC_CREDS = "JARVIS_GSC_CREDENTIALS_JSON"  # path to service account JSON
ENV_GA4_PROPERTY = "JARVIS_GA4_PROPERTY_ID"
ENV_GA4_CREDS = "JARVIS_GA4_CREDENTIALS_JSON"
ENV_GA4_BOOKING_EVENT = "JARVIS_GA4_BOOKING_EVENT_NAME"
ENV_ADS_CUSTOMER = "JARVIS_GOOGLE_ADS_CUSTOMER_ID"
ENV_ADS_DEV_TOKEN = "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN"
ENV_ADS_CREDS = "JARVIS_GOOGLE_ADS_CREDENTIALS_JSON"
ENV_MARKETING_SITE = "JARVIS_MARKETING_SITE_URL"
ENV_ADC = "GOOGLE_APPLICATION_CREDENTIALS"  # shared ADC path
ENV_LIVE = "JARVIS_MARKETING_LIVE_APIS"

# Flip to True when live read adapters are implemented (still read-only).
_MARKETING_ADAPTERS_IMPLEMENTED = False


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _has_file_path(p: str) -> bool:
    if not p:
        return False
    try:
        return os.path.isfile(p)
    except OSError:
        return False


def marketing_live_apis_enabled() -> bool:
    v = (_env(ENV_LIVE) or "").lower()
    return v in ("1", "true", "yes", "on")


def _creds_ok(*paths: str) -> bool:
    for p in paths:
        if _has_file_path(_env(p)):
            return True
    if _has_file_path(_env(ENV_ADC)):
        return True
    return False


def gsc_status() -> dict[str, Any]:
    site = _env(ENV_GSC_SITE)
    configured = bool(site) and _creds_ok(ENV_GSC_CREDS)
    available = bool(
        configured and marketing_live_apis_enabled() and _MARKETING_ADAPTERS_IMPLEMENTED
    )
    msg = "Not configured: set JARVIS_GSC_SITE_URL and JARVIS_GSC_CREDENTIALS_JSON (or GOOGLE_APPLICATION_CREDENTIALS)."
    if configured and not marketing_live_apis_enabled():
        msg = "Search Console credentials are configured; live API reads are not enabled in this build (JARVIS_MARKETING_LIVE_APIS)."
    if configured and marketing_live_apis_enabled() and not _MARKETING_ADAPTERS_IMPLEMENTED:
        msg = "Search Console env is ready; marketing API adapters are not implemented in this build yet."
    if available:
        msg = "Search Console reads are available (read-only)."
    return {
        "source": "google_search_console",
        "configured": configured,
        "available": available,
        "message": msg,
    }


def ga4_status() -> dict[str, Any]:
    prop = _env(ENV_GA4_PROPERTY)
    configured = bool(prop) and _creds_ok(ENV_GA4_CREDS)
    available = bool(
        configured and marketing_live_apis_enabled() and _MARKETING_ADAPTERS_IMPLEMENTED
    )
    msg = "Not configured: set JARVIS_GA4_PROPERTY_ID and JARVIS_GA4_CREDENTIALS_JSON (or GOOGLE_APPLICATION_CREDENTIALS)."
    if configured and not marketing_live_apis_enabled():
        msg = "GA4 property is configured; live API reads are not enabled in this build (JARVIS_MARKETING_LIVE_APIS)."
    if configured and marketing_live_apis_enabled() and not _MARKETING_ADAPTERS_IMPLEMENTED:
        msg = "GA4 env is ready; marketing API adapters are not implemented in this build yet."
    if available:
        msg = "GA4 reads are available (read-only)."
    return {
        "source": "ga4",
        "configured": configured,
        "available": available,
        "message": msg,
    }


def google_ads_status() -> dict[str, Any]:
    cid = _env(ENV_ADS_CUSTOMER)
    dev = _env(ENV_ADS_DEV_TOKEN)
    configured = bool(cid and dev) and _creds_ok(ENV_ADS_CREDS)
    available = bool(
        configured and marketing_live_apis_enabled() and _MARKETING_ADAPTERS_IMPLEMENTED
    )
    msg = (
        "Not configured: set JARVIS_GOOGLE_ADS_CUSTOMER_ID, JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN, "
        "and JARVIS_GOOGLE_ADS_CREDENTIALS_JSON (or GOOGLE_APPLICATION_CREDENTIALS)."
    )
    if configured and not marketing_live_apis_enabled():
        msg = "Google Ads customer is configured; live API reads are not enabled in this build (JARVIS_MARKETING_LIVE_APIS)."
    if configured and marketing_live_apis_enabled() and not _MARKETING_ADAPTERS_IMPLEMENTED:
        msg = "Google Ads env is ready; marketing API adapters are not implemented in this build yet."
    if available:
        msg = "Google Ads reads are available (read-only)."
    return {
        "source": "google_ads",
        "configured": configured,
        "available": available,
        "message": msg,
    }


def site_access_status() -> dict[str, Any]:
    url = _env(ENV_MARKETING_SITE)
    configured = bool(url)
    available = configured  # URL known; no external ping in this patch
    msg = "Not configured: set JARVIS_MARKETING_SITE_URL (canonical public site for Peluquería Cruz)."
    if configured:
        msg = "Marketing site URL is configured (read-only; no live HTTP checks in this build)."
    return {
        "source": "site",
        "configured": configured,
        "available": available,
        "message": msg,
        "site_url": url or None,
    }


def list_marketing_source_statuses() -> list[dict[str, Any]]:
    return [
        gsc_status(),
        ga4_status(),
        google_ads_status(),
        site_access_status(),
    ]


def _date_range(days_back: int) -> tuple[str, str, int]:
    end = date.today()
    start = end - timedelta(days=max(1, days_back) - 1)
    return (start.isoformat(), end.isoformat(), days_back)


def _base_unavailable(
    *,
    source: str,
    reason: str,
    message: str,
    configured: bool,
    available: bool,
    days_back: int,
) -> dict[str, Any]:
    start, end, d = _date_range(days_back)
    return {
        "status": "unavailable",
        "source": source,
        "reason": reason,
        "message": message,
        "configured": configured,
        "available": available,
        "business": "Peluquería Cruz",
        "date_range": {"start": start, "end": end, "days_back": d},
    }


def fetch_search_console_summary(days_back: int) -> dict[str, Any]:
    st = gsc_status()
    if not st["configured"]:
        return _base_unavailable(
            source="google_search_console",
            reason="not_configured",
            message=st["message"],
            configured=False,
            available=False,
            days_back=days_back,
        )
    if not marketing_live_apis_enabled():
        return _base_unavailable(
            source="google_search_console",
            reason="live_apis_disabled",
            message="Set JARVIS_MARKETING_LIVE_APIS=true when ready for live read-only API calls.",
            configured=True,
            available=False,
            days_back=days_back,
        )
    if not _MARKETING_ADAPTERS_IMPLEMENTED:
        return _base_unavailable(
            source="google_search_console",
            reason="adapter_not_implemented",
            message="Search Console live adapter is not implemented yet.",
            configured=True,
            available=False,
            days_back=days_back,
        )
    # Reserved for real Search Console API (read-only).
    return _base_unavailable(
        source="google_search_console",
        reason="adapter_not_implemented",
        message="Search Console live adapter is not implemented yet.",
        configured=True,
        available=False,
        days_back=days_back,
    )


def fetch_ga4_booking_funnel(days_back: int) -> dict[str, Any]:
    st = ga4_status()
    event = _env(ENV_GA4_BOOKING_EVENT)
    if not st["configured"]:
        return _base_unavailable(
            source="ga4",
            reason="not_configured",
            message=st["message"],
            configured=False,
            available=False,
            days_back=days_back,
        )
    if not event:
        start, end, d = _date_range(days_back)
        return {
            "status": "unavailable",
            "source": "ga4",
            "reason": "missing_event_mapping",
            "message": "GA4 booking/conversion event name is not configured. Set JARVIS_GA4_BOOKING_EVENT_NAME.",
            "configured": True,
            "available": False,
            "business": "Peluquería Cruz",
            "booking_event_name": None,
            "date_range": {"start": start, "end": end, "days_back": d},
        }
    if not marketing_live_apis_enabled():
        return _base_unavailable(
            source="ga4",
            reason="live_apis_disabled",
            message="Set JARVIS_MARKETING_LIVE_APIS=true when ready for live read-only API calls.",
            configured=True,
            available=False,
            days_back=days_back,
        )
    if not _MARKETING_ADAPTERS_IMPLEMENTED:
        return _base_unavailable(
            source="ga4",
            reason="adapter_not_implemented",
            message="GA4 live funnel adapter is not implemented yet.",
            configured=True,
            available=False,
            days_back=days_back,
        )
    return _base_unavailable(
        source="ga4",
        reason="adapter_not_implemented",
        message="GA4 live funnel adapter is not implemented yet.",
        configured=True,
        available=False,
        days_back=days_back,
    )


def fetch_google_ads_summary(days_back: int) -> dict[str, Any]:
    st = google_ads_status()
    if not st["configured"]:
        return _base_unavailable(
            source="google_ads",
            reason="not_configured",
            message=st["message"],
            configured=False,
            available=False,
            days_back=days_back,
        )
    if not marketing_live_apis_enabled():
        return _base_unavailable(
            source="google_ads",
            reason="live_apis_disabled",
            message="Set JARVIS_MARKETING_LIVE_APIS=true when ready for live read-only API calls.",
            configured=True,
            available=False,
            days_back=days_back,
        )
    if not _MARKETING_ADAPTERS_IMPLEMENTED:
        return _base_unavailable(
            source="google_ads",
            reason="adapter_not_implemented",
            message="Google Ads live adapter is not implemented yet.",
            configured=True,
            available=False,
            days_back=days_back,
        )
    return _base_unavailable(
        source="google_ads",
        reason="adapter_not_implemented",
        message="Google Ads live adapter is not implemented yet.",
        configured=True,
        available=False,
        days_back=days_back,
    )


def fetch_top_pages_by_conversion(days_back: int, limit: int) -> dict[str, Any]:
    """
    Strongest/weakest pages by conversion behavior requires GA4 (and booking event mapping) in this layer.
    """
    st = ga4_status()
    event = _env(ENV_GA4_BOOKING_EVENT)
    if not st["configured"]:
        return _base_unavailable(
            source="ga4",
            reason="not_configured",
            message=st["message"],
            configured=False,
            available=False,
            days_back=days_back,
        )
    if not event:
        start, end, d = _date_range(days_back)
        return {
            "status": "unavailable",
            "source": "ga4",
            "reason": "missing_event_mapping",
            "message": "Cannot rank pages by conversion without JARVIS_GA4_BOOKING_EVENT_NAME.",
            "configured": True,
            "available": False,
            "business": "Peluquería Cruz",
            "date_range": {"start": start, "end": end, "days_back": d},
            "limit": limit,
        }
    if not marketing_live_apis_enabled():
        out = _base_unavailable(
            source="ga4",
            reason="live_apis_disabled",
            message="Set JARVIS_MARKETING_LIVE_APIS=true when ready for live read-only API calls.",
            configured=True,
            available=False,
            days_back=days_back,
        )
        out["limit"] = limit
        return out
    if not _MARKETING_ADAPTERS_IMPLEMENTED:
        out = _base_unavailable(
            source="ga4",
            reason="adapter_not_implemented",
            message="GA4 top-pages-by-conversion adapter is not implemented yet.",
            configured=True,
            available=False,
            days_back=days_back,
        )
        out["limit"] = limit
        return out
    out = _base_unavailable(
        source="ga4",
        reason="adapter_not_implemented",
        message="GA4 top-pages-by-conversion adapter is not implemented yet.",
        configured=True,
        available=False,
        days_back=days_back,
    )
    out["limit"] = limit
    return out


def build_search_console_ok_sample(*, days_back: int) -> dict[str, Any]:
    """Test helper: stable positive-path payload (no external I/O)."""
    start, end, d = _date_range(days_back)
    return {
        "status": "ok",
        "source": "google_search_console",
        "business": "Peluquería Cruz",
        "configured": True,
        "available": True,
        "message": "Stubbed summary for tests.",
        "date_range": {"start": start, "end": end, "days_back": d},
        "aggregate": {
            "clicks": 1200,
            "impressions": 45000,
            "ctr": 0.0267,
            "position": 14.2,
        },
        "top_queries": [
            {"query": "peluquería cruz", "clicks": 80, "impressions": 1200, "ctr": 0.067, "position": 4.1},
            {"query": "corte pelo", "clicks": 40, "impressions": 900, "ctr": 0.044, "position": 8.3},
        ],
        "top_pages": [
            {
                "page": "https://example.com/",
                "clicks": 300,
                "impressions": 8000,
                "ctr": 0.0375,
                "position": 6.2,
            },
        ],
    }


def build_search_console_opportunity_sample(*, days_back: int) -> dict[str, Any]:
    """Test helper: high impressions + low CTR rows to trigger heuristic opportunities."""
    start, end, d = _date_range(days_back)
    return {
        "status": "ok",
        "source": "google_search_console",
        "business": "Peluquería Cruz",
        "date_range": {"start": start, "end": end, "days_back": d},
        "top_queries": [
            {"query": "peluquería barrio", "clicks": 10, "impressions": 2000, "ctr": 0.005, "position": 12.0},
        ],
        "top_pages": [
            {
                "page": "https://example.com/book",
                "clicks": 50,
                "impressions": 5000,
                "ctr": 0.01,
                "position": 10.0,
            },
        ],
        "aggregate": {"clicks": 60, "impressions": 7000, "ctr": 0.0086, "position": 11.0},
    }


def build_google_ads_waste_sample(*, days_back: int) -> dict[str, Any]:
    """Test helper: active campaign with spend and zero conversions."""
    start, end, d = _date_range(days_back)
    return {
        "status": "ok",
        "source": "google_ads",
        "business": "Peluquería Cruz",
        "date_range": {"start": start, "end": end, "days_back": d},
        "campaigns": [
            {
                "name": "Generic Search",
                "status": "ENABLED",
                "cost": 200.0,
                "spend": 200.0,
                "clicks": 80,
                "impressions": 9000,
                "conversions": 0.0,
                "cpc": 2.5,
                "cpa": None,
            },
        ],
        "aggregate": {"cost": 200.0, "conversions": 0.0, "clicks": 80},
    }


def build_top_pages_gap_sample(*, days_back: int, limit: int = 10) -> dict[str, Any]:
    """Test helper: strongest vs weakest pages for conversion gap heuristic."""
    start, end, d = _date_range(days_back)
    return {
        "status": "ok",
        "source": "ga4",
        "business": "Peluquería Cruz",
        "date_range": {"start": start, "end": end, "days_back": d},
        "limit": limit,
        "strongest": [
            {"page": "https://example.com/book", "conversion_rate": 0.08, "sessions": 120},
        ],
        "weakest": [
            {"page": "https://example.com/blog/hair-tips", "conversion_rate": 0.002, "sessions": 6000},
        ],
    }
