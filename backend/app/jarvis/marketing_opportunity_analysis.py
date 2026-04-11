"""
Deterministic, read-only synthesis of marketing fetch outputs into opportunity analysis.

Calls :mod:`app.jarvis.marketing_sources` fetch helpers only (no duplicate I/O logic).
No LLM. Bounded heuristics.
"""

from __future__ import annotations

from typing import Any

from app.jarvis.marketing_sources import (
    fetch_ga4_booking_funnel,
    fetch_google_ads_summary,
    fetch_search_console_summary,
    fetch_top_pages_by_conversion,
    list_marketing_source_statuses,
)

BUSINESS = "Peluquería Cruz"

# Heuristic thresholds (tunable; keep simple and explainable)
_MIN_IMPRESSIONS_LOW_CTR_QUERY = 400
_MAX_CTR_OPPORTUNITY_QUERY = 0.035
_MIN_IMPRESSIONS_LOW_CTR_PAGE = 800
_MAX_CTR_OPPORTUNITY_PAGE = 0.03
_MIN_SPEND_WASTE_ADS = 50.0
_MAX_CONVERSIONS_WASTE_ADS = 0
_STRONG_SPEND_WASTE_ADS = 120.0
_MAX_CONVERSIONS_WEAK_ADS = 1


def _stable_item(
    *,
    type_: str,
    title: str,
    summary: str,
    source: str,
    page: str | None = None,
    campaign: str | None = None,
    metric: str | None = None,
    value: Any = None,
    priority: str | None = None,
) -> dict[str, Any]:
    return {
        "type": type_,
        "title": title,
        "summary": summary,
        "source": source,
        "page": page,
        "campaign": campaign,
        "metric": metric,
        "value": value,
        "priority": priority,
    }


def _missing_entry(
    *,
    type_: str,
    title: str,
    summary: str,
    source: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return _stable_item(
        type_=type_,
        title=title,
        summary=summary,
        source=source,
        metric="availability",
        value=reason,
        priority="high",
    )


def _is_data_ok(payload: dict[str, Any]) -> bool:
    return (payload or {}).get("status") == "ok"


def _append_gsc_opportunities(
    gsc: dict[str, Any],
    *,
    top_n: int,
    out: list[dict[str, Any]],
) -> None:
    if not _is_data_ok(gsc):
        return
    queries = gsc.get("top_queries") or []
    for q in queries:
        if len(out) >= top_n:
            return
        imps = float(q.get("impressions") or 0)
        ctr = float(q.get("ctr") or 0)
        if imps >= _MIN_IMPRESSIONS_LOW_CTR_QUERY and ctr <= _MAX_CTR_OPPORTUNITY_QUERY:
            out.append(
                _stable_item(
                    type_="seo_ctr",
                    title=f"Low CTR on query: {q.get('query')!r}",
                    summary=(
                        "High impressions with relatively low CTR — review title/snippet and intent match."
                    ),
                    source="google_search_console",
                    metric="ctr",
                    value=ctr,
                    priority="medium",
                )
            )
    pages = gsc.get("top_pages") or []
    for p in pages:
        if len(out) >= top_n:
            return
        imps = float(p.get("impressions") or 0)
        ctr = float(p.get("ctr") or 0)
        page_url = str(p.get("page") or "")
        if imps >= _MIN_IMPRESSIONS_LOW_CTR_PAGE and ctr <= _MAX_CTR_OPPORTUNITY_PAGE:
            out.append(
                _stable_item(
                    type_="seo_page_ctr",
                    title="Landing page with visibility but weak CTR",
                    summary="Page earns impressions; improving meta description and on-page relevance may lift clicks.",
                    source="google_search_console",
                    page=page_url or None,
                    metric="ctr",
                    value=ctr,
                    priority="medium",
                )
            )


def _append_ads_wastes(
    ads: dict[str, Any],
    *,
    top_n: int,
    out: list[dict[str, Any]],
) -> None:
    if not _is_data_ok(ads):
        return
    campaigns = ads.get("campaigns") or []
    for c in campaigns:
        if len(out) >= top_n:
            return
        name = str(c.get("name") or c.get("campaign") or "campaign")
        status = str(c.get("status") or "").upper()
        spend = float(c.get("cost") or c.get("spend") or 0)
        conv = float(c.get("conversions") or 0)
        if status and status not in ("ENABLED", "ACTIVE", "2"):
            continue
        if spend >= _MIN_SPEND_WASTE_ADS and conv <= _MAX_CONVERSIONS_WASTE_ADS:
            out.append(
                _stable_item(
                    type_="sem_spend_no_conv",
                    title=f"Spend without conversions: {name}",
                    summary="Active campaign spent budget with no attributed conversions in-window — review targeting and LP alignment.",
                    source="google_ads",
                    campaign=name,
                    metric="conversions",
                    value=conv,
                    priority="high",
                )
            )
        elif spend >= _STRONG_SPEND_WASTE_ADS and conv <= _MAX_CONVERSIONS_WEAK_ADS:
            out.append(
                _stable_item(
                    type_="sem_weak_conv",
                    title=f"High spend, very low conversions: {name}",
                    summary="Consider tightening keywords/negatives and validating conversion tracking.",
                    source="google_ads",
                    campaign=name,
                    metric="conversions",
                    value=conv,
                    priority="high",
                )
            )


def _append_conversion_gaps(
    pages: dict[str, Any],
    gsc: dict[str, Any],
    *,
    top_n: int,
    out: list[dict[str, Any]],
) -> None:
    if _is_data_ok(pages):
        weakest = pages.get("weakest") or pages.get("bottom") or []
        strongest = pages.get("strongest") or pages.get("top") or []
        best_rate = None
        if strongest:
            try:
                best_rate = max(float(x.get("conversion_rate") or 0) for x in strongest)
            except ValueError:
                best_rate = None
        for w in weakest:
            if len(out) >= top_n:
                return
            url = str(w.get("page") or w.get("landing_page") or "")
            sessions = float(w.get("sessions") or w.get("users") or 0)
            cr = float(w.get("conversion_rate") or 0)
            if sessions >= 200 and cr <= 0.01 and (best_rate is None or cr < best_rate * 0.25):
                out.append(
                    _stable_item(
                        type_="conversion_gap_page",
                        title="High-traffic page with weak conversion rate",
                        summary="Sessions are meaningful but conversion rate lags stronger pages — prioritize CTA and trust signals.",
                        source="ga4",
                        page=url or None,
                        metric="conversion_rate",
                        value=cr,
                        priority="high",
                    )
                )
        return

    # Partial: GSC traffic but no GA4 conversion page ranking
    if _is_data_ok(gsc) and not _is_data_ok(pages):
        tp = gsc.get("top_pages") or []
        for p in tp[:3]:
            if len(out) >= top_n:
                return
            clicks = float(p.get("clicks") or 0)
            page_url = str(p.get("page") or "")
            if clicks >= 80:
                out.append(
                    _stable_item(
                        type_="traffic_without_conv_context",
                        title="Strong organic traffic; conversion context missing",
                        summary=(
                            "Search traffic exists for this URL, but GA4 conversion/page ranking data "
                            "was unavailable — connect booking event mapping to compare traffic vs bookings."
                        ),
                        source="google_search_console",
                        page=page_url or None,
                        metric="clicks",
                        value=clicks,
                        priority="medium",
                    )
                )


def _collect_missing_data(
    *,
    gsc: dict[str, Any],
    ga4: dict[str, Any],
    ads: dict[str, Any],
    pages: dict[str, Any],
    statuses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []

    def _add_from_fetch(label: str, src: str, payload: dict[str, Any]) -> None:
        if _is_data_ok(payload):
            return
        reason = str(payload.get("reason") or "unavailable")
        missing.append(
            _missing_entry(
                type_="source_unavailable",
                title=f"{label} data not available",
                summary=str(payload.get("message") or ""),
                source=src,
                reason=reason,
            )
        )

    _add_from_fetch("Search Console", "google_search_console", gsc)
    _add_from_fetch("GA4 funnel", "ga4", ga4)
    _add_from_fetch("Google Ads", "google_ads", ads)
    _add_from_fetch("Top pages by conversion", "ga4", pages)

    if (ga4 or {}).get("reason") == "missing_event_mapping" or (pages or {}).get(
        "reason"
    ) == "missing_event_mapping":
        missing.append(
            _missing_entry(
                type_="missing_event_mapping",
                title="Booking/conversion event not mapped",
                summary="Set JARVIS_GA4_BOOKING_EVENT_NAME to unlock funnel and page conversion analysis.",
                source="ga4",
                reason="missing_event_mapping",
            )
        )

    for st in statuses:
        src = str(st.get("source") or "")
        if src == "site":
            continue
        if not st.get("configured"):
            missing.append(
                _missing_entry(
                    type_="not_configured",
                    title=f"{src} not configured",
                    summary=str(st.get("message") or ""),
                    source=src,
                    reason="not_configured",
                )
            )

    # Dedupe by (type, source, title) — simple
    seen: set[tuple[str, str, str]] = set()
    uniq: list[dict[str, Any]] = []
    for m in missing:
        key = (str(m.get("type")), str(m.get("source")), str(m.get("title")))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(m)
    return uniq


def _recommended_checks(
    *,
    available: list[str],
    missing_data: list[dict[str, Any]],
    gsc: dict[str, Any],
    ga4: dict[str, Any],
    ads: dict[str, Any],
    pages: dict[str, Any],
    top_n: int,
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    if "google_search_console" not in available:
        recs.append(
            _stable_item(
                type_="configure_gsc",
                title="Enable Search Console summaries",
                summary="Configure GSC site + credentials to unlock query/page CTR diagnostics.",
                source="google_search_console",
                priority="high",
            )
        )
    if "ga4" not in available or (ga4 or {}).get("reason") == "missing_event_mapping":
        recs.append(
            _stable_item(
                type_="map_booking_event",
                title="Map GA4 booking event",
                summary="Define JARVIS_GA4_BOOKING_EVENT_NAME so funnel and landing-page gaps can be quantified.",
                source="ga4",
                priority="high",
            )
        )
    if "google_ads" not in available:
        recs.append(
            _stable_item(
                type_="configure_ads",
                title="Enable Google Ads read access",
                summary="Configure Ads customer + developer token + credentials for spend/conversion efficiency review.",
                source="google_ads",
                priority="medium",
            )
        )
    if _is_data_ok(gsc) and not _is_data_ok(pages):
        recs.append(
            _stable_item(
                type_="cross_channel",
                title="Connect SEO traffic to conversion data",
                summary="With GSC live, add GA4 conversion mapping to relate rankings to bookings.",
                source="ga4",
                priority="medium",
            )
        )
    if _is_data_ok(ads) and not _is_data_ok(ga4):
        recs.append(
            _stable_item(
                type_="validate_attribution",
                title="Validate Ads vs GA4 conversion consistency",
                summary="Ads data is present; ensure GA4 funnel uses the same booking event for comparable CPA.",
                source="google_ads",
                priority="medium",
            )
        )
    # Fill with generic items if still short
    if not recs:
        recs.append(
            _stable_item(
                type_="baseline",
                title="Establish marketing data connections",
                summary="Configure GSC, GA4, and Google Ads read access for full Peluquería Cruz analysis.",
                source="marketing",
                priority="low",
            )
        )
    return recs[:top_n]


def run_analyze_marketing_opportunities(*, days_back: int, top_n: int) -> dict[str, Any]:
    gsc = fetch_search_console_summary(days_back)
    ga4 = fetch_ga4_booking_funnel(days_back)
    ads = fetch_google_ads_summary(days_back)
    pages = fetch_top_pages_by_conversion(days_back, limit=min(50, max(10, top_n * 4)))
    statuses = list_marketing_source_statuses()

    available: list[str] = []
    if _is_data_ok(gsc):
        available.append("google_search_console")
    if _is_data_ok(ga4):
        available.append("ga4")
    if _is_data_ok(ads):
        available.append("google_ads")
    if _is_data_ok(pages):
        available.append("ga4_top_pages")

    unavailable: list[dict[str, Any]] = []
    for label, src, payload in (
        ("google_search_console", "google_search_console", gsc),
        ("ga4_funnel", "ga4", ga4),
        ("google_ads", "google_ads", ads),
        ("top_pages_by_conversion", "ga4", pages),
    ):
        if _is_data_ok(payload):
            continue
        unavailable.append(
            {
                "key": label,
                "source": src,
                "reason": payload.get("reason"),
                "message": payload.get("message"),
            }
        )

    opportunities: list[dict[str, Any]] = []
    wastes: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    _append_gsc_opportunities(gsc, top_n=top_n, out=opportunities)
    _append_ads_wastes(ads, top_n=top_n, out=wastes)
    _append_conversion_gaps(pages, gsc, top_n=top_n, out=gaps)

    missing_data = _collect_missing_data(
        gsc=gsc, ga4=ga4, ads=ads, pages=pages, statuses=statuses
    )

    recommended = _recommended_checks(
        available=available,
        missing_data=missing_data,
        gsc=gsc,
        ga4=ga4,
        ads=ads,
        pages=pages,
        top_n=top_n,
    )

    sources_checked = [
        "google_search_console",
        "ga4",
        "google_ads",
        "ga4_top_pages",
        "marketing_source_status",
    ]

    has_signal = bool(available or opportunities or wastes or gaps or missing_data)
    overall_status: str = "ok" if has_signal else "insufficient_data"

    return {
        "status": overall_status,
        "business": BUSINESS,
        "days_back": days_back,
        "top_n": top_n,
        "sources_checked": sources_checked,
        "available_sources": available,
        "unavailable_sources": unavailable,
        "biggest_opportunities": opportunities[:top_n],
        "biggest_wastes": wastes[:top_n],
        "conversion_gaps": gaps[:top_n],
        "missing_data": missing_data,
        "recommended_next_checks": recommended[:top_n],
    }
