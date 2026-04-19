"""Read-only GA4 Data API analytics for Jarvis missions (no mutations)."""

from __future__ import annotations

import os
from typing import Any

_LAST_30 = ("30daysAgo", "today")


def _safe_float(value: str | None) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ga4_readonly_insights(
    pages: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> tuple[list[str], list[str], str]:
    """Deterministic issues/opportunities from top pages and events."""
    issues: list[str] = []
    opps: list[str] = []

    if pages:
        top = pages[0]
        top_sessions = int(top.get("sessions") or 0)
        top_er = _safe_float(str(top.get("engagement_rate") or "0"))
        top_conv = _safe_float(str(top.get("conversions") or "0"))
        path = str(top.get("path") or "")[:120] or str(top.get("title") or "top page")
        if top_sessions >= 30 and top_er > 0 and top_er < 0.25:
            issues.append(f"Low engagement rate ({top_er:.0%}) on high-traffic page '{path}' ({top_sessions} sessions).")
        if top_sessions >= 50 and top_conv == 0.0:
            issues.append(f"High sessions ({top_sessions}) but zero conversions on '{path}' — check funnel or tagging.")
        if len(pages) >= 2:
            second = pages[1]
            s2 = int(second.get("sessions") or 0)
            if top_sessions > 0 and s2 > 0 and top_sessions > 5 * s2:
                issues.append("Strong concentration: top page draws far more sessions than the rest — diversification risk.")

        best_er_page = max(pages, key=lambda p: _safe_float(str(p.get("engagement_rate") or "0")))
        if _safe_float(str(best_er_page.get("engagement_rate") or "0")) >= 0.55 and int(best_er_page.get("sessions") or 0) >= 10:
            nm = str(best_er_page.get("path") or best_er_page.get("title") or "page")[:100]
            opps.append(f"Study '{nm}' — highest engagement rate among top pages; replicate patterns elsewhere.")

    if events:
        ev_top = events[0]
        ec = int(ev_top.get("event_count") or 0)
        conv = _safe_float(str(ev_top.get("conversions") or "0"))
        en = str(ev_top.get("name") or "event")[:80]
        if ec >= 500 and conv == 0.0 and en.lower() not in ("session_start", "first_visit", "page_view"):
            issues.append(f"Event '{en}' has high volume ({ec}) but reports zero conversions — validate conversion mapping.")
        if conv > 0 and ec >= 50:
            opps.append(f"Event '{en}' shows measurable conversions — prioritize quality and volume on this path.")

    if not issues:
        if pages:
            issues.append("No major red flags in the top-page snapshot; monitor week-over-week deltas.")
        elif events:
            issues.append("No major red flags in the top-event snapshot; monitor week-over-week deltas.")
        else:
            issues.append("Limited signal in the 30-day window; verify data collection.")
    if not opps:
        if pages:
            opps.append("Compare top pages by sessions vs. engagement rate to find quick UX or content wins.")
        elif events:
            opps.append("Compare top events by volume vs. conversions to tune tracking and UX.")
        else:
            opps.append("Expand reporting once traffic and events accumulate in this window.")

    total_sessions = sum(int(p.get("sessions") or 0) for p in pages)
    total_events = sum(int(e.get("event_count") or 0) for e in events)
    summary = (
        f"Last 30 days (read-only): {len(pages)} top pages, {len(events)} top events by volume; "
        f"~{total_sessions} summed sessions across shown pages; ~{total_events} summed event counts across shown events."
    )
    return issues[:4], opps[:4], summary


def _row_to_page_dict(dim_vals: list[str], met_vals: list[str], dim_names: list[str], met_names: list[str]) -> dict[str, Any]:
    d = {dim_names[i]: dim_vals[i] for i in range(min(len(dim_names), len(dim_vals)))}
    m = {met_names[i]: met_vals[i] for i in range(min(len(met_names), len(met_vals)))}
    return {
        "path": str(d.get("pagePath") or "").strip() or "(not set)",
        "title": str(d.get("pageTitle") or "").strip() or "",
        "sessions": int(float(m.get("sessions") or 0)),
        "users": int(float(m.get("totalUsers") or 0)),
        "event_count": int(float(m.get("eventCount") or 0)),
        "engagement_rate": _safe_float(m.get("engagementRate")),
        "conversions": _safe_float(m.get("conversions")),
    }


def _row_to_event_dict(dim_vals: list[str], met_vals: list[str], dim_names: list[str], met_names: list[str]) -> dict[str, Any]:
    d = {dim_names[i]: dim_vals[i] for i in range(min(len(dim_names), len(dim_vals)))}
    m = {met_names[i]: met_vals[i] for i in range(min(len(met_names), len(met_vals)))}
    return {
        "name": str(d.get("eventName") or "").strip() or "(not set)",
        "event_count": int(float(m.get("eventCount") or 0)),
        "users": int(float(m.get("totalUsers") or 0)),
        "conversions": _safe_float(m.get("conversions")),
    }


def _parse_property_id(raw: str) -> str | None:
    s = (raw or "").strip()
    if s.startswith("properties/"):
        s = s.split("/", 1)[-1]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None


def run_ga4_readonly_analytics(params: dict[str, Any]) -> dict[str, Any]:
    """
    Run two read-only GA4 Data API reports: top pages and top events (last 30 days).

    Env / params:
      - property_id or JARVIS_GA4_PROPERTY_ID
      - credentials_json or JARVIS_GA4_CREDENTIALS_JSON (service account JSON path)
      - limit (default 10)
    """
    limit = int(params.get("limit") or 10)
    if limit < 1:
        limit = 10
    if limit > 100:
        limit = 100

    prop_raw = str(params.get("property_id") or os.getenv("JARVIS_GA4_PROPERTY_ID") or "").strip()
    property_id = _parse_property_id(prop_raw)
    cred_path = str(params.get("credentials_json") or os.getenv("JARVIS_GA4_CREDENTIALS_JSON") or "").strip()

    base: dict[str, Any] = {
        "analytics_period": "last_30_days",
        "ga4_analytics_fetch_ok": False,
        "analytics_top_pages": [],
        "analytics_top_events": [],
        "analytics_summary": "",
        "analytics_issues": [],
        "analytics_opportunities": [],
        "analytics_query_error": None,
    }

    if not property_id:
        base["analytics_query_error"] = "GA4 property ID is missing (JARVIS_GA4_PROPERTY_ID)."
        return base
    if not cred_path or not os.path.isfile(cred_path):
        base["analytics_query_error"] = f"GA4 credentials file not found or not a file: {cred_path!r}."
        return base

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, OrderBy, RunReportRequest
    except Exception as exc:
        base["analytics_query_error"] = f"GA4 client library import failed: {exc}"
        return base

    try:
        client = BetaAnalyticsDataClient.from_service_account_file(cred_path)
    except Exception as exc:
        base["analytics_query_error"] = f"GA4 credentials could not be loaded: {exc}"[:800]
        return base

    prop = f"properties/{property_id}"
    date_ranges = [DateRange(start_date=_LAST_30[0], end_date=_LAST_30[1])]

    page_dims = ["pagePath", "pageTitle"]
    page_metric_sets = [
        ["sessions", "totalUsers", "eventCount", "engagementRate", "conversions"],
        ["sessions", "totalUsers", "eventCount"],
    ]
    event_dims = ["eventName"]
    event_metric_sets = [
        ["eventCount", "totalUsers", "conversions"],
        ["eventCount", "totalUsers"],
    ]

    pages_out: list[dict[str, Any]] = []
    events_out: list[dict[str, Any]] = []
    err_parts: list[str] = []

    def _run_one(
        dimensions: list[str],
        metrics: list[str],
        order_metric: str,
        *,
        is_page: bool,
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            req = RunReportRequest(
                property=prop,
                date_ranges=date_ranges,
                dimensions=[Dimension(name=n) for n in dimensions],
                metrics=[Metric(name=n) for n in metrics],
                order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name=order_metric), desc=True)],
                limit=limit,
            )
            resp = client.run_report(req)
        except Exception as exc:
            return [], str(exc)[:600]

        dim_headers = [h.name for h in resp.dimension_headers]
        met_headers = [h.name for h in resp.metric_headers]
        rows_out: list[dict[str, Any]] = []
        for row in resp.rows or []:
            dvals = [dv.value for dv in row.dimension_values]
            mvals = [mv.value for mv in row.metric_values]
            if is_page:
                rows_out.append(_row_to_page_dict(dvals, mvals, dim_headers, met_headers))
            else:
                rows_out.append(_row_to_event_dict(dvals, mvals, dim_headers, met_headers))
        return rows_out, None

    e1: str | None = None
    for pm in page_metric_sets:
        pages_out, e1 = _run_one(page_dims, pm, "sessions", is_page=True)
        if not e1:
            break
    if e1:
        err_parts.append(f"pages_report: {e1}")

    e2: str | None = None
    for em in event_metric_sets:
        events_out, e2 = _run_one(event_dims, em, "eventCount", is_page=False)
        if not e2:
            break
    if e2:
        err_parts.append(f"events_report: {e2}")

    if err_parts:
        base["analytics_query_error"] = "; ".join(err_parts)
        base["ga4_analytics_fetch_ok"] = False
        base["analytics_top_pages"] = pages_out
        base["analytics_top_events"] = events_out
        return base

    issues, opps, summary = _ga4_readonly_insights(pages_out, events_out)
    base["ga4_analytics_fetch_ok"] = True
    base["analytics_top_pages"] = pages_out
    base["analytics_top_events"] = events_out
    base["analytics_issues"] = issues
    base["analytics_opportunities"] = opps
    base["analytics_summary"] = summary
    return base
