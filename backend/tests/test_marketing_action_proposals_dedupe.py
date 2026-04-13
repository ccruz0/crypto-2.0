"""Tests for marketing missing-data dedupe and proposal shaping (no Bedrock / no live tools)."""

from __future__ import annotations

from app.jarvis.marketing_action_proposals import (
    _drop_redundant_unavailable_proposals,
    build_proposals_from_analysis,
    dedupe_missing_data_entries,
)


def test_dedupe_drops_source_unavailable_when_not_configured_present() -> None:
    md = [
        {
            "type": "not_configured",
            "source": "google_search_console",
            "title": "google_search_console not configured",
        },
        {
            "type": "source_unavailable",
            "source": "google_search_console",
            "title": "Search Console data not available",
        },
    ]
    out = dedupe_missing_data_entries(md)
    assert len(out) == 1
    assert out[0]["type"] == "not_configured"
    assert "Google Search Console" in out[0]["title"]


def test_dedupe_collapses_multiple_ga4_source_unavailable() -> None:
    md = [
        {"type": "source_unavailable", "source": "ga4", "title": "Funnel missing"},
        {"type": "source_unavailable", "source": "ga4", "title": "Top pages missing"},
    ]
    out = dedupe_missing_data_entries(md)
    assert len(out) == 1
    assert "Google Analytics" in out[0]["title"]
    assert "funnel" in out[0]["title"].lower()


def test_build_proposals_no_duplicate_gsc_unavailable_after_dedupe() -> None:
    analysis = {
        "status": "insufficient_data",
        "business": "T",
        "available_sources": [],
        "biggest_opportunities": [],
        "biggest_wastes": [],
        "conversion_gaps": [],
        "missing_data": [
            {
                "type": "not_configured",
                "source": "google_search_console",
                "title": "google_search_console not configured",
            },
            {
                "type": "source_unavailable",
                "source": "google_search_console",
                "title": "Noise",
            },
        ],
        "unavailable_sources": [],
    }
    r = build_proposals_from_analysis(analysis, days_back=7, top_n=10)
    titles = [p["title"] for p in r["proposed_actions"]]
    assert sum(1 for t in titles if "data not available" in t.lower()) == 0
    assert any("Connect" in t and "Google Search Console" in t for t in titles)


def test_drop_redundant_unavailable_proposals_strips_parallel_data_gap() -> None:
    """Safety net: same source should not list Connect and a generic data-unavailable action."""
    props = [
        {
            "title": "Connect Google Search Console for Peluquería Cruz",
            "source": "google_search_console",
            "action_type": "connect_data_source",
        },
        {
            "title": "Google Search Console data not available",
            "source": "google_search_console",
            "action_type": "connect_data_source",
        },
    ]
    out = _drop_redundant_unavailable_proposals(props)
    assert len(out) == 1
    assert out[0]["title"].startswith("Connect ")


def test_setup_connect_sorts_before_same_priority_opportunity() -> None:
    analysis = {
        "status": "ok",
        "business": "T",
        "available_sources": ["google_ads"],
        "biggest_opportunities": [
            {
                "type": "seo_ctr",
                "source": "google_search_console",
                "page": "/x",
                "priority": "medium",
                "summary": "s",
            }
        ],
        "biggest_wastes": [],
        "conversion_gaps": [],
        "missing_data": [
            {
                "type": "not_configured",
                "source": "ga4",
                "title": "ga4 not configured",
            },
        ],
        "unavailable_sources": [],
    }
    r = build_proposals_from_analysis(analysis, days_back=28, top_n=5)
    titles = [p["title"] for p in r["proposed_actions"]]
    assert titles[0].startswith("Connect ")
