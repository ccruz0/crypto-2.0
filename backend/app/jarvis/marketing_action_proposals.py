"""
Deterministic mapping from :func:`run_analyze_marketing_opportunities` output to proposed actions.

Read-only. No LLM. Intended for future approval/execution routing.
"""

from __future__ import annotations

from typing import Any

from app.jarvis.marketing_opportunity_analysis import run_analyze_marketing_opportunities

_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}

# Human-readable names for connect/setup proposals (avoid raw env keys in titles).
_SOURCE_LABELS = {
    "google_search_console": "Google Search Console",
    "ga4": "Google Analytics",
    "google_ads": "Google Ads",
    "ga4_top_pages": "Google Analytics",
    "marketing": "Marketing",
}


def _friendly_source_label(src: str) -> str:
    s = (src or "").strip().lower()
    return _SOURCE_LABELS.get(s, s.replace("_", " ").title())


def dedupe_missing_data_entries(missing_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove overlapping missing-data rows for the same source.

    If ``not_configured`` or ``missing_event_mapping`` exists for a source, drop
    ``source_unavailable`` rows for that source (setup is the real action).
    Collapse multiple ``source_unavailable`` rows for one source (e.g. GA4 funnel + top pages)
    into a single executive line.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for m in missing_data:
        if not isinstance(m, dict):
            continue
        src = str(m.get("source") or "").strip().lower()
        if not src:
            src = "_none"
        groups.setdefault(src, []).append(m)

    out: list[dict[str, Any]] = []
    for src, items in groups.items():
        types = [str(x.get("type") or "") for x in items]
        has_strong = any(t in ("not_configured", "missing_event_mapping") for t in types)
        if has_strong:
            items = [x for x in items if str(x.get("type") or "") != "source_unavailable"]

        su = [x for x in items if str(x.get("type") or "") == "source_unavailable"]
        rest = [x for x in items if str(x.get("type") or "") != "source_unavailable"]

        if len(su) > 1:
            first = dict(su[0])
            if src == "ga4":
                first["title"] = "Google Analytics data not available (funnel / top pages)"
            elif src == "google_search_console":
                first["title"] = "Google Search Console data not available"
            elif src == "google_ads":
                first["title"] = "Google Ads data not available"
            else:
                first["title"] = str(su[0].get("title") or "Data not available")
            su = [first]

        out.extend(rest)
        out.extend(su)

    for x in out:
        if str(x.get("type")) == "not_configured":
            src = str(x.get("source") or "")
            t = str(x.get("title") or "")
            if src and t == f"{src} not configured":
                x["title"] = f"{_friendly_source_label(src)} not configured"

    return out


def _drop_redundant_unavailable_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    If a ``Connect <source>`` setup action exists, drop generic ``data not available`` proposals
    for the same source (near-duplicates).
    """
    connect_sources: set[str] = set()
    for p in proposals:
        title = str(p.get("title") or "")
        if title.startswith("Connect ") and "Peluquería" in title:
            connect_sources.add(str(p.get("source") or "").strip().lower())

    out: list[dict[str, Any]] = []
    for p in proposals:
        src = str(p.get("source") or "").strip().lower()
        title_l = str(p.get("title") or "").lower()
        if src in connect_sources and (
            "data not available" in title_l or title_l.endswith(" not available")
        ):
            continue
        out.append(p)
    return out


def _proposed_action(
    *,
    action_type: str,
    title: str,
    summary: str,
    source: str,
    target: str | None,
    reason: str,
    priority: str,
    suggested_channel: str,
    requires_human_review: bool = True,
    supporting_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "action_type": action_type,
        "title": title,
        "summary": summary,
        "source": source,
        "target": target,
        "reason": reason,
        "priority": priority,
        "suggested_channel": suggested_channel,
        "requires_human_review": requires_human_review,
        "supporting_metrics": supporting_metrics,
    }


def _supporting_from_finding(f: dict[str, Any]) -> dict[str, Any] | None:
    m = f.get("metric")
    if not m:
        return None
    out: dict[str, Any] = {"metric": m}
    if f.get("value") is not None:
        out["value"] = f.get("value")
    return out


def _map_opportunity_finding(f: dict[str, Any]) -> dict[str, Any]:
    t = str(f.get("type") or "")
    src = str(f.get("source") or "google_search_console")
    sup = _supporting_from_finding(f)
    page = f.get("page")
    if t == "seo_ctr":
        return _proposed_action(
            action_type="improve_seo_snippet",
            title="Improve search snippet for high-impression query",
            summary=(
                "Rewrite title and meta description so the SERP snippet better matches search intent "
                "and lifts CTR without changing rankings."
            ),
            source=src,
            target=str(f.get("title") or "query"),
            reason="High impressions with low CTR indicate snippet/title mismatch.",
            priority="medium",
            suggested_channel="search_console",
            supporting_metrics=sup,
        )
    if t == "seo_page_ctr":
        return _proposed_action(
            action_type="improve_meta_description",
            title="Improve meta description for visible URL",
            summary="Tune page title/description and on-SERP relevance to increase clicks from existing impressions.",
            source=src,
            target=page if isinstance(page, str) else None,
            reason="URL earns impressions but CTR is below peer threshold.",
            priority="medium",
            suggested_channel="search_console",
            supporting_metrics=sup,
        )
    return _proposed_action(
        action_type="improve_page_title",
        title=f"Review SEO finding: {t}",
        summary=str(f.get("summary") or "Address the identified SEO opportunity."),
        source=src,
        target=page if isinstance(page, str) else None,
        reason=str(f.get("summary") or ""),
        priority=str(f.get("priority") or "medium"),
        suggested_channel="search_console",
        supporting_metrics=sup,
    )


def _map_waste_finding(f: dict[str, Any]) -> dict[str, Any]:
    t = str(f.get("type") or "")
    campaign = f.get("campaign")
    camp_s = str(campaign) if campaign else None
    sup = _supporting_from_finding(f)
    if t == "sem_spend_no_conv":
        return _proposed_action(
            action_type="pause_or_reduce_budget",
            title="Pause or reduce budget on zero-conversion spend",
            summary=(
                "Reduce waste by lowering budgets or pausing until targeting, creatives, and "
                "conversion tracking are validated."
            ),
            source="google_ads",
            target=camp_s,
            reason="Active spend with zero attributed conversions in the analysis window.",
            priority="high",
            suggested_channel="google_ads",
            supporting_metrics=sup,
        )
    if t == "sem_weak_conv":
        return _proposed_action(
            action_type="review_campaign_targeting",
            title="Tighten campaign targeting and negatives",
            summary="Add negative keywords, narrow match types or audiences, and verify landing page match.",
            source="google_ads",
            target=camp_s,
            reason="High spend with critically low conversions.",
            priority="high",
            suggested_channel="google_ads",
            supporting_metrics=sup,
        )
    return _proposed_action(
        action_type="add_negative_keywords",
        title="Review Ads efficiency",
        summary=str(f.get("summary") or "Improve campaign efficiency."),
        source="google_ads",
        target=camp_s,
        reason=str(f.get("summary") or ""),
        priority="medium",
        suggested_channel="google_ads",
        supporting_metrics=sup,
    )


def _map_gap_finding(f: dict[str, Any]) -> dict[str, Any]:
    t = str(f.get("type") or "")
    page = f.get("page")
    page_s = str(page) if isinstance(page, str) else None
    sup = _supporting_from_finding(f)
    if t == "conversion_gap_page":
        return _proposed_action(
            action_type="improve_landing_page_cta",
            title="Strengthen CTA and trust on underperforming page",
            summary="Improve primary CTA placement, copy, and mobile UX; add social proof near the conversion action.",
            source=str(f.get("source") or "ga4"),
            target=page_s,
            reason="High sessions with weak conversion rate vs stronger pages.",
            priority="high",
            suggested_channel="ga4",
            supporting_metrics=sup,
        )
    if t == "traffic_without_conv_context":
        return _proposed_action(
            action_type="review_page_message_match",
            title="Align landing page with organic intent",
            summary=(
                "Ensure headline and offer match the queries driving traffic; then wire GA4 booking events "
                "to measure impact."
            ),
            source=str(f.get("source") or "google_search_console"),
            target=page_s,
            reason="Organic traffic exists but conversion/booking context was not available in GA4.",
            priority="medium",
            suggested_channel="search_console",
            supporting_metrics=sup,
        )
    return _proposed_action(
        action_type="improve_booking_flow",
        title="Address conversion gap",
        summary=str(f.get("summary") or ""),
        source=str(f.get("source") or "ga4"),
        target=page_s,
        reason=str(f.get("summary") or ""),
        priority="medium",
        suggested_channel="ga4",
        supporting_metrics=sup,
    )


def _map_missing_data_item(m: dict[str, Any]) -> dict[str, Any]:
    t = str(m.get("type") or "")
    src = str(m.get("source") or "")
    reason = str(m.get("value") or m.get("reason") or "")
    title = str(m.get("title") or "Data gap")

    if t == "missing_event_mapping" or reason == "missing_event_mapping":
        return _proposed_action(
            action_type="configure_ga4_booking_event",
            title="Configure GA4 booking/conversion event",
            summary=(
                "Set JARVIS_GA4_BOOKING_EVENT_NAME (and verify the event fires) so funnel and "
                "landing-page analysis can run."
            ),
            source="ga4",
            target="booking_event",
            reason="Booking or conversion event is not mapped for Jarvis marketing analysis.",
            priority="high",
            suggested_channel="ga4",
            supporting_metrics=None,
        )
    if t == "not_configured":
        label = _friendly_source_label(src)
        return _proposed_action(
            action_type="connect_data_source",
            title=f"Connect {label} for Peluquería Cruz",
            summary=str(m.get("summary") or "Add credentials and property identifiers in environment configuration."),
            source=src,
            target=src,
            reason="Source is not configured for read-only marketing tools.",
            priority="medium",
            suggested_channel="ops",
            supporting_metrics={"reason": reason} if reason else None,
        )
    # source_unavailable and others
    return _proposed_action(
        action_type="connect_data_source",
        title=title,
        summary=str(m.get("summary") or "Restore data access for this channel."),
        source=src or "marketing",
        target=src or None,
        reason=reason or "Data not available for this analysis window.",
        priority="medium",
        suggested_channel="ops",
        supporting_metrics={"reason": reason} if reason else None,
    )


def _derive_analysis_status(analysis: dict[str, Any]) -> str:
    avail = set(analysis.get("available_sources") or [])
    need = {"google_search_console", "ga4", "google_ads", "ga4_top_pages"}
    if avail >= need:
        return "full"
    if analysis.get("status") == "insufficient_data" and not avail:
        return "insufficient_data"
    return "partial"


def build_proposals_from_analysis(
    analysis: dict[str, Any], *, days_back: int, top_n: int
) -> dict[str, Any]:
    """
    Map a single :func:`run_analyze_marketing_opportunities` result to proposed actions
    without re-fetching sources (used by orchestration pipelines).
    """
    business = analysis.get("business") or "Peluquería Cruz"
    unavailable = list(analysis.get("unavailable_sources") or [])
    missing_data = dedupe_missing_data_entries(list(analysis.get("missing_data") or []))

    proposals: list[dict[str, Any]] = []

    for f in analysis.get("biggest_opportunities") or []:
        proposals.append(_map_opportunity_finding(f))

    for f in analysis.get("biggest_wastes") or []:
        proposals.append(_map_waste_finding(f))

    for f in analysis.get("conversion_gaps") or []:
        proposals.append(_map_gap_finding(f))

    for m in missing_data:
        proposals.append(_map_missing_data_item(m))

    proposals = _drop_redundant_unavailable_proposals(proposals)

    def _sort_key(p: dict[str, Any]) -> tuple[int, int, str]:
        pr = str(p.get("priority") or "low")
        pri = -_PRIORITY_RANK.get(pr, 0)
        t = str(p.get("title") or "")
        setup_first = 0 if (t.startswith("Connect ") or "Configure GA4" in t) else 1
        return (setup_first, pri, str(p.get("action_type") or ""))

    proposals.sort(key=_sort_key)
    proposals = proposals[: max(0, top_n)]

    analysis_status = _derive_analysis_status(analysis)
    overall_status: str = "ok" if proposals else "insufficient_data"

    return {
        "status": overall_status,
        "business": business,
        "days_back": days_back,
        "top_n": top_n,
        "analysis_status": analysis_status,
        "proposed_actions": proposals,
        "missing_data": missing_data,
        "unavailable_sources": unavailable,
    }


def run_propose_marketing_actions(*, days_back: int, top_n: int) -> dict[str, Any]:
    analysis = run_analyze_marketing_opportunities(days_back=days_back, top_n=top_n)
    return build_proposals_from_analysis(analysis, days_back=days_back, top_n=top_n)
