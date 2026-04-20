"""Read-only analytics prompt gates (shared by planner, execution, and goal satisfaction)."""

from __future__ import annotations

import re

_CRITICAL_PATTERN = re.compile(
    r"\b(deploy|delete|drop|withdraw|transfer|trade|buy|sell|shutdown|restart|rotate secret)\b",
    re.IGNORECASE,
)
_READ_ONLY_SCOPE = re.compile(
    r"\b(read[-\s]?only|read\s+only|analysis only|report only|do not (change|modify|edit|write)|"
    r"non[-\s]?destructive|solo\s+lectura|sólo\s+lectura|únicamente\s+lectura|"
    r"sin\s+cambios|no\s+modificar)\b",
    re.IGNORECASE,
)
_TIME_SCOPE = re.compile(
    r"\b(last|past|previous)\s+\d+\s*(days?|weeks?|months?)\b",
    re.IGNORECASE,
)
# Spanish / mixed explicit windows ("últimos 30 días", "en los últimos 14 días")
_TIME_SCOPE_ES = re.compile(
    r"\b((?:últim|pasad)[oa]s?\s+\d+\s*(?:d[ií]as?|semanas?|meses?)|"
    r"(?:de\s+)?en\s+los\s+últimos\s+\d+\s*d[ií]as?|"
    r"de\s+los\s+últimos\s+\d+\s*d[ií]as?)\b",
    re.IGNORECASE,
)
_TOP_RANK = re.compile(r"\btop\s+(\d+)\b", re.IGNORECASE)
_TOP_RANK_ES = re.compile(
    r"\bprimer(?:as|os)?\s+(\d+)\b|"
    r"\blas\s+(\d+)\s+(?:primeras?|principales?|campa[nñ]as?)\b|"
    r"\btop\s+(\d+)\s+campa[nñ]as?\b",
    re.IGNORECASE,
)

# Google Ads–oriented tokens (two hits required when domain is google_ads on strict path).
_ANALYTICS_METRICS_ADS = re.compile(
    r"\b(spend|impressions?|clicks?|ctr|conversions?|cost|roas|campaigns?|metrics|"
    r"campa[nñ]as?|m[ée]tricas?|gasto|conversiones?|clics?|impresiones?)\b",
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

# Underspecified but safe Google Ads read-only analytics (Spanish/English): review / weak / pause advice.
_GOOGLE_ADS_RELAXED_LEX = re.compile(
    r"(campa[nñ]as?|campaigns?|m[ée]tricas?|metrics?|rendimiento|performance|"
    r"gasto|spend|conversiones?|conversions?|clics?|clicks?|ctr|impresiones?|impressions?|roas|"
    r"revis\w*|review\w*|analiz\w*|analyz\w*|informe|report|identif\w*|debil|weak|oportunidad|opportunity|"
    r"deber[ií]a|dime|cu[eé]ntame|objetivos?|cuenta|pausar|pause\b)",
    re.IGNORECASE,
)
_GOOGLE_ADS_REVIEW_VERB = re.compile(
    r"\b(revis|review|analiz|analyz|\bdime\b|\bcu[eé]ntame\b|"
    r"identific|informe|report|evalu|assess|debil|weak|oportunidad|opportunity|"
    r"deber[ií]a\s+paus|should\s+pause|hay\s+algun|hay\s+alguna|any\s+that|"
    r"qu[eé]\s+(?:opinas|recomiendas|sugieres))\w*",
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


def extract_explicit_timeframe_phrase(prompt: str) -> str | None:
    """Matched explicit timeframe text (EN/ES) or None."""
    text = (prompt or "").strip()
    m = _TIME_SCOPE.search(text)
    if m:
        return m.group(0).lower().replace("  ", " ")
    m2 = _TIME_SCOPE_ES.search(text)
    if m2:
        return m2.group(0).lower().replace("  ", " ")
    return None


def extract_explicit_top_rank(prompt: str) -> int | None:
    """Explicit top-N limit from prompt (EN/ES) or None."""
    text = (prompt or "").strip()
    m = _TOP_RANK.search(text)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return None
    m2 = _TOP_RANK_ES.search(text)
    if m2:
        for g in m2.groups():
            if g:
                try:
                    return int(g)
                except (TypeError, ValueError):
                    continue
    return None


def explicit_timeframe_in_prompt(prompt: str) -> bool:
    return extract_explicit_timeframe_phrase(prompt) is not None


def explicit_top_rank_in_prompt(prompt: str) -> bool:
    return extract_explicit_top_rank(prompt) is not None


def _has_explicit_timeframe(text: str) -> bool:
    return explicit_timeframe_in_prompt(text)


def _has_explicit_top_rank(text: str) -> bool:
    return explicit_top_rank_in_prompt(text)


def _strict_readonly_analytics_prompt_sufficient(text: str, low: str) -> bool:
    """Original strict rubric (GA4/GSC + fully specified Google Ads)."""
    if not _READ_ONLY_SCOPE.search(low):
        return False
    if not _has_explicit_timeframe(text):
        return False
    if not _has_explicit_top_rank(text):
        return False
    if not _ANALYTICS_DOMAIN.search(low):
        return False
    domain = detect_readonly_analytics_domain(text)
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


def _google_ads_relaxed_readonly_analytics(text: str, low: str) -> bool:
    """
    Safe underspecified Google Ads read-only analytics (no English last-N-days / top-N required).

    Still requires read-only scope, clear Google Ads + review/analysis intent, and enough signal
    to avoid vague 'do something with Ads' prompts.
    """
    if "google ads" not in low and "ads account" not in low:
        return False
    if not _READ_ONLY_SCOPE.search(low):
        return False
    if not _GOOGLE_ADS_REVIEW_VERB.search(low):
        return False
    if len(_GOOGLE_ADS_RELAXED_LEX.findall(low)) < 2:
        return False
    return True


def readonly_analytics_prompt_sufficient(prompt: str) -> bool:
    """True when prompt is specific enough for strict read-only analytics rubrics and planner relax."""
    text = (prompt or "").strip()
    if len(text) < 48:
        return False
    if _CRITICAL_PATTERN.search(text):
        return False
    low = text.lower()
    if not _ANALYTICS_DOMAIN.search(low):
        return False
    if _strict_readonly_analytics_prompt_sufficient(text, low):
        return True
    domain = detect_readonly_analytics_domain(prompt)
    if domain == "google_ads" and _google_ads_relaxed_readonly_analytics(text, low):
        return True
    return False
