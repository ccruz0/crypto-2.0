"""Read-only analytics prompt gates (shared by planner, execution, and goal satisfaction)."""

from __future__ import annotations

import re

_CRITICAL_PATTERN = re.compile(
    r"\b(deploy|delete|drop|withdraw|transfer|trade|buy|sell|shutdown|restart|rotate secret)\b",
    re.IGNORECASE,
)
_READ_ONLY_SCOPE = re.compile(
    r"\b(read[-\s]?only|read\s+only|analysis only|report only|do not (change|modify|edit|write)|"
    r"non[-\s]?destructive)\b",
    re.IGNORECASE,
)
_TIME_SCOPE = re.compile(
    r"\b(last|past|previous)\s+\d+\s*(days?|weeks?|months?)\b",
    re.IGNORECASE,
)
_TOP_RANK = re.compile(r"\btop\s+\d+\b", re.IGNORECASE)

# Google Ads–oriented tokens (two hits required when domain is google_ads).
_ANALYTICS_METRICS_ADS = re.compile(
    r"\b(spend|impressions?|clicks?|ctr|conversions?|cost|roas|campaigns?|metrics)\b",
    re.IGNORECASE,
)
# GA4-oriented tokens.
_ANALYTICS_METRICS_GA4 = re.compile(
    r"\b(pages?|events?|sessions?|users?|metrics|conversions?|clicks?|impressions?|engagement|traffic)\b",
    re.IGNORECASE,
)
# Search Console–oriented tokens.
_ANALYTICS_METRICS_GSC = re.compile(
    r"\b(queries?|pages?|clicks?|impressions?|ctr|position|metrics|search)\b",
    re.IGNORECASE,
)

_ANALYTICS_DOMAIN = re.compile(
    r"\b(google\s+ads|ads\s+account|ga4|google\s+analytics|search\s+console|\bgsc\b)\b",
    re.IGNORECASE,
)


def detect_readonly_analytics_domain(prompt: str) -> str | None:
    """Return primary analytics domain: google_ads, ga4, or gsc (priority: Ads > GA4 > GSC)."""
    low = (prompt or "").lower()
    if "google ads" in low or "ads account" in low:
        return "google_ads"
    if "ga4" in low or "google analytics" in low:
        return "ga4"
    if "search console" in low or re.search(r"\bgsc\b", low):
        return "gsc"
    return None


def readonly_analytics_prompt_sufficient(prompt: str) -> bool:
    """True when prompt is specific enough for strict read-only analytics rubrics and planner relax."""
    text = (prompt or "").strip()
    if len(text) < 48:
        return False
    if _CRITICAL_PATTERN.search(text):
        return False
    low = text.lower()
    if not _READ_ONLY_SCOPE.search(low):
        return False
    if not _TIME_SCOPE.search(low):
        return False
    if not _TOP_RANK.search(low):
        return False
    if not _ANALYTICS_DOMAIN.search(low):
        return False
    domain = detect_readonly_analytics_domain(prompt)
    if domain == "google_ads":
        if len(_ANALYTICS_METRICS_ADS.findall(low)) < 2:
            return False
    elif domain == "ga4":
        if len(_ANALYTICS_METRICS_GA4.findall(low)) < 2:
            return False
    elif domain == "gsc":
        if len(_ANALYTICS_METRICS_GSC.findall(low)) < 2:
            return False
    else:
        return False
    return True
