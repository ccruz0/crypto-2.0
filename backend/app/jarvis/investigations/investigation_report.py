"""Investigation report format, validation, and root-cause ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.jarvis.investigations.confidence import (
    apply_confidence_regression_caps,
    calibrate_confidence,
)
from app.jarvis.investigations.domains import (
    InvestigationDomain,
    apply_domain_gating,
    classify_cause_domain,
    classify_domain,
    domain_relevance,
    objective_aware_rc_enabled,
)
from app.jarvis.investigations.evidence_model import (
    EvidenceItem,
    count_independent_sources,
    evidence_weight,
    has_direct_evidence,
    identify_missing_evidence,
    is_substantive_evidence,
    merge_evidence,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.jarvis.investigations.recommendation_builder import build_recommendation_plan

_EMPTY_VALUES = frozenset({"", "none", "null", "n/a", "not determined", "unknown"})

_GENERIC_ROOT_CAUSE_PHRASES = frozenset(
    {
        "unknown",
        "not determined",
        "unable to determine",
        "could not determine",
        "insufficient data",
        "needs further investigation",
        "requires further investigation",
        "no root cause found",
        "collect additional evidence",
        "n/a",
    }
)

_RESOLVED_MISMATCH_CAUSE = "No active dashboard/exchange mismatch detected"


@dataclass
class RootCauseCandidate:
    cause: str
    score: float
    supporting_evidence: list[str] = field(default_factory=list)
    explanation: str = ""
    domain: str = ""


@dataclass(frozen=True)
class OpenOrdersClassification:
    """Resolved vs active open-order mismatch state derived from live counts."""

    active_mismatch: bool
    root_cause: str
    score: float
    impact: str
    recommended_fix: str
    next_action: str
    notes: tuple[str, ...] = ()
    trigger_warning: str | None = None
    resolution: str = "active"  # "resolved" | "active"


_NO_ACTIVE_MISMATCH = "No active dashboard/exchange mismatch detected"

_DB_COVERAGE_NOTE = (
    "DB stores regular open-status rows (NEW/ACTIVE/PARTIALLY_FILLED); "
    "dashboard cache includes advanced/trigger orders from unified exchange fetch"
)

_TRIGGER_50001_WARNING = (
    "Trigger-order API returned error_code=50001 (non-fatal; regular orders synced successfully)"
)

_HISTORICAL_CAUSE_MARKERS = (
    "trigger order api failure blocks cache",
    "reconciliation found",
    "open order counts differ",
    "database has open orders but dashboard cache is empty",
    "database has pending orders but",
    "api cache returned 0",
)


@dataclass
class InvestigationReport:
    investigation_id: str
    objective: str
    category: str
    template_id: str
    status: InvestigationStatus
    summary: str
    evidence: list[EvidenceItem]
    root_cause: str | None
    confidence: float
    ranked_causes: list[RootCauseCandidate]
    impact: str
    recommended_fix: str
    verification_steps: list[str]
    next_action: str
    created_at: str
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    collector_failures: list[str] = field(default_factory=list)
    resolution_status: str | None = None
    synthesis: dict[str, Any] = field(default_factory=dict)
    missing_evidence: list[str] = field(default_factory=list)
    domain: str = ""
    confidence_breakdown: dict[str, Any] = field(default_factory=dict)
    recommendation_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "investigation_id": self.investigation_id,
            "objective": self.objective,
            "category": self.category,
            "template_id": self.template_id,
            "status": self.status.value,
            "summary": self.summary,
            "evidence": self.evidence,
            "evidence_count": len(self.evidence),
            "root_cause": self.root_cause,
            "confidence": self.confidence,
            "ranked_causes": [
                {
                    "cause": c.cause,
                    "score": c.score,
                    "supporting_evidence": c.supporting_evidence,
                    "explanation": c.explanation,
                }
                for c in self.ranked_causes
            ],
            "impact": self.impact,
            "recommended_fix": self.recommended_fix,
            "verification_steps": self.verification_steps,
            "next_action": self.next_action,
            "created_at": self.created_at,
            "tool_results": self.tool_results,
            "collector_failures": self.collector_failures,
            "passed": self.status == InvestigationStatus.COMPLETED,
            "synthesis": self.synthesis,
            "missing_evidence": self.missing_evidence,
            "evidence_sources": sorted({e["source"] for e in self.evidence if is_substantive_evidence(e)}),
        }
        if self.resolution_status:
            payload["resolution_status"] = self.resolution_status
        # Objective-aware fields (populated only when the feature flag is on).
        if self.domain:
            payload["domain"] = self.domain
        if self.confidence_breakdown:
            payload["confidence_breakdown"] = self.confidence_breakdown
        if self.recommendation_plan:
            payload["recommendation_plan"] = self.recommendation_plan
        return payload


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in _EMPTY_VALUES


def _is_meaningful_root_cause(value: Any) -> bool:
    if not _is_present(value):
        return False
    text = str(value).strip().lower()
    if text in _GENERIC_ROOT_CAUSE_PHRASES:
        return False
    if len(text) < 12:
        return False
    return True


def _has_explicit_domain_evidence(
    evidence: list[EvidenceItem],
    cause_domain: InvestigationDomain,
) -> bool:
    """True when a direct, high-confidence evidence item is itself in the cause domain.

    Backs the design's "explicit evidence override": a cross-domain cause may only
    be promoted when there is direct high-confidence evidence of that domain.
    """
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if item.get("is_direct") and str(item.get("confidence")) == "high":
            if classify_cause_domain(str(item.get("detail", ""))) == cause_domain:
                return True
    return False


def _confidence_level(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _format_evidence_for_synthesis(evidence: list[EvidenceItem]) -> list[str]:
    lines: list[str] = []
    for item in evidence:
        if not is_substantive_evidence(item):
            continue
        parts = [f"[{item['source']}|{item['confidence']}] {item['detail'][:200]}"]
        if item.get("table"):
            parts.append(f"table={item['table']}")
        if item.get("row_count") is not None:
            parts.append(f"rows={item['row_count']}")
        if item.get("order_ids"):
            parts.append(f"order_ids={item['order_ids'][:5]}")
        if item.get("exchange_response_code"):
            parts.append(f"exchange_code={item['exchange_response_code']}")
        if item.get("file_path"):
            parts.append(f"path={item['file_path']}:{item.get('line_number', '')}")
        lines.append("; ".join(parts))
    return lines[:12]


def build_synthesis(
    *,
    objective: str,
    evidence: list[EvidenceItem],
    root_cause: str | None,
    impact: str,
    next_action: str,
    confidence: float,
    missing_evidence: list[str],
) -> dict[str, Any]:
    """Build structured final synthesis sections for an investigation."""
    evidence_found = _format_evidence_for_synthesis(evidence)
    summary = objective
    if root_cause:
        summary = f"{objective}\n\nConclusion: {root_cause}"
    return {
        "summary": summary,
        "evidence_found": evidence_found,
        "root_cause": root_cause or "",
        "impact": impact,
        "safe_recommended_next_action": next_action,
        "missing_evidence": missing_evidence,
        "confidence_level": _confidence_level(confidence),
        "confidence_score": confidence,
        "independent_source_count": count_independent_sources(evidence),
    }


# Known production root-cause patterns with matchers.
_KNOWN_CAUSE_PATTERNS: list[dict[str, Any]] = [
    {
        "cause": "FILLED orders exist in database but dashboard trade history does not display them",
        "fix": "Verify trade-history API route returns FILLED exchange_orders rows and frontend renders them.",
        "impact": "Executed trades visible in DB or Crypto.com may be absent from dashboard trade history.",
        "verification": [
            "Run count_orders_by_status preset and confirm FILLED count.",
            "Inspect recent_trade_events rows for expected BTC order IDs.",
            "Check routes_orders trade-history handler and frontend trade tab filters.",
        ],
        "matchers": [
            re.compile(r"FILLED\s*=\s*[1-9]|status_counts.*FILLED", re.I),
            re.compile(r"executed\s+orders?\s+missing|filled\s+orders?\s+missing", re.I),
            re.compile(r"recent_trade_events|trade.?history", re.I),
        ],
        "category": "orders",
    },
    {
        "cause": "Trigger order API failure blocks cache updates",
        "fix": "Allow regular open orders to update cache independently when trigger-order sync fails.",
        "impact": "Dashboard shows zero open orders while exchange has active regular orders.",
        "verification": [
            "Confirm trigger_orders_error_code=50001 in sync metadata.",
            "Verify exchange has regular orders and dashboard cache count is 0.",
            "Re-run reconcile_crypto_com_open_orders after fix deployment.",
        ],
        "matchers": [
            re.compile(r"trigger.?order.*50001|50001.*trigger", re.I),
            re.compile(r"trigger_orders_error_code.*50001", re.I),
            re.compile(r"exchange=\d+.*dashboard=0|exchange.*1.*dashboard.*0", re.I),
            re.compile(r"cache update.*abort|trigger.*sync.*fail", re.I),
        ],
        "category": "orders",
    },
    {
        "cause": "Crypto.com API credentials missing or misconfigured in runtime.env",
        "fix": "Set canonical EXCHANGE_CUSTOM_API_KEY/SECRET in runtime.env; remove duplicate secret lines.",
        "impact": "Private exchange API calls fail; sync and dashboard data may be empty or stale.",
        "verification": [
            "Confirm credential_diagnostics shows expected used_pair.",
            "Verify reconcile reports missing_credentials or 40101 in logs.",
            "Re-test private API after credential cleanup.",
        ],
        "matchers": [
            re.compile(r"missing_credentials|credentials not configured", re.I),
            re.compile(r"40101|authentication\s+fail", re.I),
            re.compile(r"api\s+credentials?\s+not\s+configured", re.I),
        ],
        "category": "authentication",
    },
    {
        "cause": "Duplicated API secret in runtime.env causes Crypto.com auth failure (40101)",
        "fix": "Remove duplicate EXCHANGE_CUSTOM_API_SECRET entries from runtime.env; keep a single canonical pair.",
        "impact": "Exchange sync fails; dashboard may show stale or empty data.",
        "verification": [
            "Inspect runtime.env for duplicate secret lines.",
            "Confirm credential_diagnostics shows multiple _PRESENT flags.",
            "Re-test Crypto.com private API after secret cleanup.",
        ],
        "matchers": [
            re.compile(r"40101|authentication\s+fail", re.I),
            re.compile(r"multiple\s+credential|duplicat.*secret", re.I),
            re.compile(r"EXCHANGE_CUSTOM_API_SECRET.*PRESENT.*CRYPTO_COM", re.I),
        ],
        "category": "authentication",
    },
    {
        "cause": "Portfolio equity derived from balances because exchange API omits equity field",
        "fix": "Map exchange-reported equity/net_equity from get_account_summary response into portfolio_cache.",
        "impact": "Dashboard portfolio total may differ from exchange-reported net equity.",
        "verification": [
            "Compare portfolio_cache total_usd vs exchange account summary equity.",
            "Inspect API response for missing equity/net_equity fields.",
        ],
        "matchers": [
            re.compile(r"equity.*derived|derived.*equity", re.I),
            re.compile(r"missing\s+equity|no\s+equity\s+field", re.I),
            re.compile(r"portfolio.*mismatch|wallet.*balance.*wrong", re.I),
        ],
        "category": "portfolio",
    },
    {
        "cause": "Database has open orders but dashboard cache is empty",
        "fix": "Run exchange sync to populate open_orders_cache; verify sync credentials and trigger-order handling.",
        "impact": "Dashboard shows empty open orders despite DB rows.",
        "verification": [
            "Compare exchange_orders open-status count vs cache count.",
            "Check exchange_sync logs for cache write failures.",
        ],
        "matchers": [
            re.compile(r"database.*cache.*empty|db.*\d+.*cache.*0", re.I),
            re.compile(r"pending orders but.*cache is empty", re.I),
        ],
        "category": "orders",
    },
    {
        "cause": "All sources agree: zero open orders on exchange",
        "fix": "No fix required unless open orders are expected on Crypto.com.",
        "impact": "Dashboard correctly reflects empty exchange state.",
        "verification": [
            "Confirm exchange live API returns zero open orders.",
            "Verify DB and cache also report zero.",
        ],
        "matchers": [
            re.compile(r"all sources agree.*zero|zero open orders", re.I),
            re.compile(r"exchange=0.*db=0.*dashboard=0", re.I),
        ],
        "category": "orders",
    },
    {
        "cause": "Stale dashboard cache not refreshed by exchange sync",
        "fix": "Trigger portfolio/open-orders cache refresh via approved sync process.",
        "impact": "Dashboard displays outdated balances or order counts.",
        "verification": [
            "Check cache last_updated timestamp vs current time.",
            "Review exchange_sync scheduler logs.",
        ],
        "matchers": [
            re.compile(r"stale\s+cache|cache.*stale|last_updated", re.I),
            re.compile(r"not refreshed|outdated", re.I),
        ],
        "category": "dashboard",
    },
    {
        "cause": "Websocket price feed disconnected or not receiving updates",
        "fix": "Restart market-updater service and verify websocket subscription health.",
        "impact": "Prices on dashboard lag behind live market.",
        "verification": [
            "Check websocket connection logs.",
            "Compare last price update timestamp vs market time.",
        ],
        "matchers": [
            re.compile(r"websocket.*disconnect|ws.*stale|price.*stale", re.I),
        ],
        "category": "websocket",
    },
    {
        "cause": "Deployment health check failing",
        "fix": "Inspect container logs and restore failing service before traffic resumes.",
        "impact": "API endpoints may return errors or degraded responses.",
        "verification": [
            "Run inspect_health on all endpoints.",
            "Check docker compose service status.",
        ],
        "matchers": [
            re.compile(r"health.*degraded|unhealthy|status=degraded", re.I),
        ],
        "category": "deployment",
    },
]


def _evidence_corpus(evidence: list[EvidenceItem], tool_outputs: list[dict[str, Any]] | None = None) -> str:
    parts = [f"{e['source']}|{e['reference']}|{e['detail']}" for e in evidence]
    for output in tool_outputs or []:
        for key in ("root_cause", "conclusion", "next_action", "error"):
            val = output.get(key)
            if _is_present(val):
                parts.append(str(val))
    return "\n".join(parts)


def _score_pattern_match(pattern: re.Pattern[str], corpus: str, evidence: list[EvidenceItem]) -> tuple[float, list[str]]:
    supporting: list[str] = []
    score = 0.0
    if pattern.search(corpus):
        score += 40.0
        supporting.append(f"Pattern match: {pattern.pattern[:60]}")
    for item in evidence:
        blob = f"{item['source']} {item['reference']} {item['detail']}"
        if pattern.search(blob):
            score += 15.0 * evidence_weight(item)
            supporting.append(f"[{item['source']}] {item['detail'][:100]}")
    return score, supporting


def _cross_source_bonus(evidence: list[EvidenceItem], supporting: list[str]) -> float:
    sources = {e["source"] for e in evidence if any(s in supporting for s in (e["detail"][:50],))}
    if len(sources) >= 3:
        return 20.0
    if len(sources) >= 2:
        return 10.0
    unique_sources_in_evidence = len({e["source"] for e in evidence})
    if unique_sources_in_evidence >= 3:
        return 8.0
    return 0.0


def _reconcile_output(tool_outputs: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for output in tool_outputs or []:
        if output.get("tool") == "reconcile_crypto_com_open_orders" and output.get("ok") is not False:
            return output
    return None


def _diagnose_output(tool_outputs: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for output in tool_outputs or []:
        if output.get("tool") == "diagnose_open_orders" and output.get("ok") is not False:
            return output
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_open_orders_snapshot(tool_outputs: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Collect authoritative open-order counts from reconcile/diagnose tool outputs."""
    reconcile = _reconcile_output(tool_outputs)
    diagnose = _diagnose_output(tool_outputs)

    counts = (reconcile or {}).get("counts") or {}
    exchange_meta = ((reconcile or {}).get("sources") or {}).get("exchange") or {}

    exchange = _int_or_none(counts.get("exchange_live"))
    if exchange is None and diagnose:
        exchange = _int_or_none(diagnose.get("exchange_total_count"))

    dashboard = _int_or_none(counts.get("dashboard_cache"))
    if dashboard is None and diagnose:
        dashboard = _int_or_none(diagnose.get("dashboard_effective_count"))

    db_count = _int_or_none(counts.get("database_open"))
    if db_count is None and diagnose:
        db_count = _int_or_none(diagnose.get("db_open_count"))

    cache_raw = _int_or_none((diagnose or {}).get("cache_raw_count"))
    if cache_raw is None and diagnose:
        cache_raw = _int_or_none(diagnose.get("cache_open_count"))

    data_verified = False
    if diagnose is not None and diagnose.get("exchange_data_verified") is not None:
        data_verified = bool(diagnose.get("exchange_data_verified"))
    elif exchange_meta.get("data_verified") is not None:
        data_verified = bool(exchange_meta.get("data_verified"))

    trigger_code = None
    trigger_error = None
    if diagnose:
        trigger_code = diagnose.get("trigger_orders_error_code")
        trigger_error = diagnose.get("trigger_orders_error")
    if trigger_code is None:
        trigger_code = exchange_meta.get("trigger_orders_error_code")
    if trigger_error is None:
        trigger_error = exchange_meta.get("trigger_orders_error")

    return {
        "exchange_count": exchange,
        "dashboard_count": dashboard,
        "db_count": db_count,
        "cache_raw_count": cache_raw,
        "data_verified": data_verified,
        "trigger_error_code": trigger_code,
        "trigger_error": trigger_error,
        "dashboard_source": (diagnose or {}).get("dashboard_source"),
    }


def classify_open_orders_mismatch(
    tool_outputs: list[dict[str, Any]] | None,
) -> OpenOrdersClassification | None:
    """
    Classify open-order investigations as resolved (counts match) or active mismatch.

    Returns None when live counts are unavailable for classification.
    """
    snapshot = _extract_open_orders_snapshot(tool_outputs)
    exchange = snapshot.get("exchange_count")
    dashboard = snapshot.get("dashboard_count")
    db_count = snapshot.get("db_count")

    if exchange is None or dashboard is None or not snapshot.get("data_verified"):
        return None

    trigger_code = snapshot.get("trigger_error_code")
    trigger_warning = None
    if str(trigger_code) == "50001" or trigger_code == 50001:
        detail = snapshot.get("trigger_error") or "ERR_INTERNAL"
        trigger_warning = f"{_TRIGGER_50001_WARNING}: {detail}"

    if exchange == dashboard:
        notes: list[str] = []
        if db_count is not None and db_count != exchange:
            notes.append(_DB_COVERAGE_NOTE)
        return OpenOrdersClassification(
            active_mismatch=False,
            root_cause=_NO_ACTIVE_MISMATCH,
            score=96.0,
            impact="Low — live dashboard and exchange counts match.",
            recommended_fix="No dashboard/exchange sync repair needed based on current live counts.",
            next_action="Monitor trigger-order API 50001 separately if trigger metadata is needed.",
            notes=tuple(notes),
            trigger_warning=trigger_warning,
            resolution="resolved",
        )

    return OpenOrdersClassification(
        active_mismatch=True,
        root_cause="Active dashboard/exchange open-order mismatch detected",
        score=90.0,
        impact="Dashboard open-order count differs from live exchange.",
        recommended_fix="Inspect exchange sync, open_orders_cache, and resolve_open_orders fallback path.",
        next_action="Run reconcile_crypto_com_open_orders and inspect exchange_sync logs for missing order IDs.",
        notes=(),
        trigger_warning=trigger_warning,
        resolution="active",
    )


def _apply_open_orders_resolution(
    candidates: list[RootCauseCandidate],
    classification: OpenOrdersClassification | None,
) -> list[RootCauseCandidate]:
    """Suppress historical causes when live exchange and dashboard counts match."""
    if classification is None or classification.active_mismatch:
        return candidates

    filtered = [
        candidate
        for candidate in candidates
        if not any(marker in candidate.cause.lower() for marker in _HISTORICAL_CAUSE_MARKERS)
    ]

    supporting = list(classification.notes)
    if classification.trigger_warning:
        supporting.append(classification.trigger_warning)

    resolved = RootCauseCandidate(
        cause=classification.root_cause,
        score=classification.score,
        supporting_evidence=supporting,
        explanation="Live exchange and dashboard counts match; historical failure modes suppressed.",
    )
    return [resolved, *filtered]


def _filter_tool_root_causes(
    *,
    candidates: list[RootCauseCandidate],
    tool_outputs: list[dict[str, Any]] | None,
) -> list[RootCauseCandidate]:
    """Prefer reconcile over diagnose; drop stale diagnose cache-only conclusions."""
    reconcile = _reconcile_output(tool_outputs)
    diagnose = _diagnose_output(tool_outputs)
    if not reconcile and not diagnose:
        return candidates

    exchange_live = int((reconcile or {}).get("counts", {}).get("exchange_live") or 0)
    if not exchange_live and diagnose:
        exchange_live = int(diagnose.get("exchange_total_count") or 0)

    dashboard_effective = int((diagnose or {}).get("dashboard_effective_count") or 0)
    cache_raw = int((diagnose or {}).get("cache_raw_count") or (diagnose or {}).get("cache_open_count") or 0)

    stale_diagnose_markers = (
        "api cache returned 0",
        "crypto.com open orders cache is empty",
        "database has pending orders but",
    )

    filtered: list[RootCauseCandidate] = []
    for candidate in candidates:
        cause_lower = candidate.cause.lower()
        if any(marker in cause_lower for marker in stale_diagnose_markers):
            if exchange_live > 0 or dashboard_effective > 0:
                continue
        filtered.append(candidate)

    if reconcile and reconcile.get("root_cause"):
        reconcile_cause = str(reconcile["root_cause"])
        counts = reconcile.get("counts") or {}
        exchange_live = int(counts.get("exchange_live") or exchange_live)
        dashboard_cache = int(counts.get("dashboard_cache") or 0)
        dashboard_effective = int((diagnose or {}).get("dashboard_effective_count") or dashboard_cache)
        suppress_reconcile_mismatch = (
            exchange_live == dashboard_effective
            and bool((reconcile.get("sources") or {}).get("exchange", {}).get("data_verified"))
        )
        if not suppress_reconcile_mismatch and not any(c.cause == reconcile_cause for c in filtered):
            filtered.insert(
                0,
                RootCauseCandidate(
                    cause=reconcile_cause,
                    score=85.0,
                    supporting_evidence=["reconcile_crypto_com_open_orders authoritative counts"],
                    explanation="Three-way reconciliation against live exchange API.",
                ),
            )

    if exchange_live > 0 and cache_raw == 0 and dashboard_effective > 0:
        fallback_cause = "Open orders cache empty but dashboard API serves database fallback"
        if not any(fallback_cause.lower() in c.cause.lower() for c in filtered):
            filtered.insert(
                0,
                RootCauseCandidate(
                    cause=fallback_cause,
                    score=90.0,
                    supporting_evidence=[
                        f"exchange_live={exchange_live}",
                        f"dashboard_effective={dashboard_effective}",
                        f"cache_raw={cache_raw}",
                    ],
                    explanation="resolve_open_orders DB fallback active; raw cache empty is not dashboard-empty.",
                ),
            )

    return filtered or candidates


def rank_root_causes(
    *,
    evidence: list[EvidenceItem],
    category: str,
    tool_outputs: list[dict[str, Any]] | None = None,
    recent_failures: int = 0,
    objective: str = "",
    template_id: str = "",
) -> list[RootCauseCandidate]:
    """Score and rank root cause candidates from collected evidence.

    When the ``JARVIS_OBJECTIVE_AWARE_RC`` flag is enabled, candidates are
    additionally re-weighted by domain relevance to the investigation objective
    (cross-domain causes are heavily penalized). When the flag is off, ranking is
    unchanged.
    """
    corpus = _evidence_corpus(evidence, tool_outputs)
    candidates: list[RootCauseCandidate] = []

    for pattern_def in _KNOWN_CAUSE_PATTERNS:
        pat_category = pattern_def.get("category", "")
        if pat_category and pat_category != category and category not in ("api", "dashboard"):
            category_bonus = 0.0
        else:
            category_bonus = 5.0
        if pat_category == category:
            category_bonus += 15.0

        total_score = category_bonus
        all_supporting: list[str] = []
        for matcher in pattern_def["matchers"]:
            pts, supporting = _score_pattern_match(matcher, corpus, evidence)
            total_score += pts
            all_supporting.extend(supporting)

        total_score += _cross_source_bonus(evidence, all_supporting)
        total_score += min(recent_failures * 3.0, 15.0)
        total_score += min(len(evidence) * 2.0, 20.0)

        # Boost when evidence explicitly states the known failure mode.
        if "missing equity" in pattern_def["cause"].lower():
            for item in evidence:
                detail_lower = item.get("detail", "").lower()
                if (
                    "missing equity" in detail_lower
                    or "derived from balances" in detail_lower
                    or "derived from cached balances" in detail_lower
                    or "exchange-reported equity" in detail_lower
                ):
                    total_score += 25.0
                    all_supporting.append(f"[{item['source']}] explicit equity gap")

        if total_score < 5.0:
            continue

        explanation_parts = []
        if all_supporting:
            explanation_parts.append(f"Supported by {len(all_supporting)} evidence signal(s).")
        if recent_failures:
            explanation_parts.append(f"Recent log failures: {recent_failures}.")
        cross_sources = len({e["source"] for e in evidence})
        if cross_sources >= 2:
            explanation_parts.append(f"Evidence spans {cross_sources} sources.")

        candidates.append(
            RootCauseCandidate(
                cause=pattern_def["cause"],
                score=min(round(total_score, 1), 100.0),
                supporting_evidence=all_supporting[:5],
                explanation=" ".join(explanation_parts),
            )
        )

    # Extract tool-provided root causes as candidates.
    for output in tool_outputs or []:
        rc = output.get("root_cause")
        if _is_present(rc):
            candidates.append(
                RootCauseCandidate(
                    cause=str(rc),
                    score=75.0,
                    supporting_evidence=[f"Tool {output.get('tool', '?')} reported root cause"],
                    explanation="Directly reported by diagnostic tool.",
                )
            )

    candidates.sort(key=lambda c: c.score, reverse=True)
    # Deduplicate similar causes.
    seen: set[str] = set()
    deduped: list[RootCauseCandidate] = []
    for c in candidates:
        key = c.cause[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    deduped = _filter_tool_root_causes(candidates=deduped, tool_outputs=tool_outputs)
    classification = classify_open_orders_mismatch(tool_outputs)
    if classification and category in ("orders", "dashboard", "exchange"):
        deduped = _apply_open_orders_resolution(deduped, classification)

    # Objective-aware domain gating (flagged; no-op when the flag is off).
    if objective_aware_rc_enabled() and (objective or category):
        domain_classification = classify_domain(objective, category=category, template_id=template_id)
        deduped = apply_domain_gating(
            deduped,
            domain_classification.domain,
            domain_classification.domain_confidence,
        )

    return deduped[:8]


def _auth_failure_signals(
    evidence: list[EvidenceItem],
    tool_outputs: list[dict[str, Any]] | None,
) -> bool:
    """Return True when evidence shows an active authentication/credential failure."""
    for item in evidence:
        if item.get("source") not in ("authentication", "exchange", "logs"):
            continue
        detail = item.get("detail", "").lower()
        if any(
            kw in detail
            for kw in (
                "40101",
                "missing_credentials",
                "failed_auth",
                "duplicate",
                "multiple credential",
                "authentication fail",
                "credentials not configured",
            )
        ):
            return True
        if item.get("exchange_response_code") in (40101, "40101"):
            return True
    for output in tool_outputs or []:
        sync_status = output.get("sync_status")
        if sync_status in ("missing_credentials", "failed_auth"):
            return True
        exchange_meta = ((output.get("sources") or {}).get("exchange") or {})
        if exchange_meta.get("sync_status") in ("missing_credentials", "failed_auth"):
            return True
        err = str(output.get("error") or exchange_meta.get("error") or "").lower()
        if "40101" in err or ("credential" in err and "not configured" in err):
            return True
    return False


def _lookup_fix_for_cause(cause: str) -> tuple[str, str, list[str]]:
    for pattern_def in _KNOWN_CAUSE_PATTERNS:
        if pattern_def["cause"].lower() in cause.lower() or cause.lower() in pattern_def["cause"].lower():
            return (
                pattern_def.get("fix", "Review evidence and implement targeted fix."),
                pattern_def.get("impact", "Production data or sync may be incorrect."),
                pattern_def.get("verification", ["Re-run investigation after fix."]),
            )
    return (
        "Review collected evidence and implement targeted fix behind approval gate.",
        "Incident may affect dashboard accuracy or exchange sync reliability.",
        ["Re-run investigation to confirm resolution."],
    )


def build_investigation_report(
    *,
    investigation_id: str,
    objective: str,
    category: str,
    template_id: str,
    evidence: list[EvidenceItem],
    ranked_causes: list[RootCauseCandidate],
    tool_outputs: list[dict[str, Any]] | None = None,
    created_at: str,
    collector_status: InvestigationStatus | None = None,
    collector_failure_reasons: list[str] | None = None,
) -> InvestigationReport:
    """Assemble a full investigation report from evidence and ranked causes."""
    tool_results = [
        {
            "tool": output.get("tool"),
            "ok": output.get("ok", True),
            "error": output.get("error"),
            "mandatory": output.get("mandatory", True),
            "root_cause": output.get("root_cause"),
        }
        for output in (tool_outputs or [])
    ]
    failures = list(collector_failure_reasons or [])

    classification = classify_open_orders_mismatch(tool_outputs)
    if classification and category not in ("authentication", "portfolio"):
        if not classification.active_mismatch and ranked_causes:
            top_cause = ranked_causes[0].cause
            if top_cause != classification.root_cause:
                ranked_causes = _apply_open_orders_resolution(ranked_causes, classification)

    top = ranked_causes[0] if ranked_causes else None
    min_score = 15.0 if category == "portfolio" else 25.0
    root_cause: str | None = None
    confidence = 0.0
    recommended_fix = ""
    impact = ""
    verification_steps: list[str] = []
    next_action = ""

    if category == "authentication":
        auth_causes = [
            c
            for c in ranked_causes
            if any(
                kw in c.cause.lower()
                for kw in ("auth", "credential", "40101", "secret", "missing")
            )
        ]
        auth_top: RootCauseCandidate | None = None
        for item in evidence:
            if item.get("source") != "authentication":
                continue
            detail_lower = item.get("detail", "").lower()
            if "missing_credentials" in detail_lower or "credentials not configured" in detail_lower:
                auth_top = RootCauseCandidate(
                    cause="Crypto.com API credentials missing or misconfigured in runtime.env",
                    score=92.0,
                    supporting_evidence=[item["detail"][:120]],
                    explanation="Direct credential diagnostic from exchange fetch.",
                )
                break
        if auth_top is None and _auth_failure_signals(evidence, tool_outputs) and auth_causes:
            auth_top = auth_causes[0]
        if auth_top and auth_top.score >= min_score:
            root_cause = auth_top.cause
            confidence = auth_top.score
            recommended_fix, impact, verification_steps = _lookup_fix_for_cause(root_cause)
            next_action = recommended_fix
        else:
            recommended_fix = "Search exchange_sync logs for 40101 and inspect runtime.env credential pairs."
            impact = "No active authentication failure confirmed; prior errors may be historical."
            verification_steps = [
                "Search logs for 40101 or Authentication failed.",
                "Confirm credential_diagnostics used_pair matches canonical runtime.env entry.",
            ]
            next_action = "If failures persist, rotate API key and verify IP allowlist on Crypto.com."
    elif classification and not classification.active_mismatch:
        root_cause = classification.root_cause
        confidence = classification.score
        recommended_fix = classification.recommended_fix
        impact = classification.impact
        verification_steps = [
            "Confirm live exchange count matches dashboard effective count.",
            "Review DB open-status count separately from unified exchange cache.",
        ]
        if classification.trigger_warning:
            verification_steps.append(
                "Note trigger_orders_error_code=50001 as non-fatal unless trigger metadata is required."
            )
        next_action = classification.next_action
    elif top and top.score >= min_score:
        root_cause = top.cause
        confidence = top.score
        recommended_fix, impact, verification_steps = _lookup_fix_for_cause(root_cause)
        next_action = recommended_fix
    else:
        recommended_fix = "Collect additional evidence from database, logs, and exchange APIs."
        impact = "Unable to determine production impact without sufficient evidence."
        verification_steps = ["Re-run investigation with expanded log access."]
        next_action = recommended_fix

    # Build summary from evidence highlights.
    summary_lines = [objective]
    for item in evidence[:4]:
        summary_lines.append(f"- {item['detail'][:120]}")
    if classification and not classification.active_mismatch and category not in ("authentication", "portfolio"):
        summary_lines.append(f"Conclusion: {classification.root_cause}")
        for note in classification.notes:
            summary_lines.append(f"- {note}")
        if classification.trigger_warning:
            summary_lines.append(f"- Warning: {classification.trigger_warning}")
    elif root_cause:
        summary_lines.append(f"Likely cause: {root_cause}")
    if failures:
        summary_lines.append(f"Collector failures: {'; '.join(failures[:3])}")

    if not (classification and not classification.active_mismatch and category not in ("authentication", "portfolio")):
        for output in tool_outputs or []:
            if _is_present(output.get("next_action")):
                next_action = str(output["next_action"])
                break

    # Objective-aware calibration + structured recommendation (flagged; no-op when off).
    domain_value = ""
    confidence_breakdown: dict[str, Any] = {}
    recommendation_plan: dict[str, Any] = {}
    objective_mismatch = False
    legacy_confidence = confidence
    if objective_aware_rc_enabled():
        domain_classification = classify_domain(objective, category=category, template_id=template_id)
        domain_value = domain_classification.domain.value
        if root_cause:
            cause_domain = classify_cause_domain(root_cause)
            relevance = domain_relevance(
                domain_classification.domain,
                cause_domain,
                domain_classification.domain_confidence,
            )
            plan = build_recommendation_plan(
                root_cause=root_cause,
                category=category,
                evidence=evidence,
                existing_fix=recommended_fix,
                existing_verification=verification_steps,
            )
            recommendation_plan = plan.to_dict()
            if plan.proposed_fix:
                recommended_fix = plan.proposed_fix
                next_action = plan.proposed_fix
            if plan.validation_steps:
                verification_steps = list(plan.validation_steps)
            breakdown = calibrate_confidence(
                evidence=evidence,
                tool_outputs=tool_outputs,
                objective_domain=domain_classification.domain,
                objective_confidence=domain_classification.domain_confidence,
                cause_domain=cause_domain,
                specificity=plan.specificity,
                has_meaningful_root_cause=_is_meaningful_root_cause(root_cause),
            )
            breakdown = apply_confidence_regression_caps(
                breakdown,
                legacy_confidence=legacy_confidence,
                category=category,
                objective_domain=domain_classification.domain,
                objective_confidence=domain_classification.domain_confidence,
                cause_domain=cause_domain,
                root_cause=root_cause,
                evidence=evidence,
                tool_outputs=tool_outputs,
                auth_failure_signals=_auth_failure_signals(evidence, tool_outputs),
            )
            confidence = breakdown.final
            confidence_breakdown = breakdown.to_dict()
            in_domain_exists = any(
                classify_cause_domain(c.cause) == domain_classification.domain for c in ranked_causes
            )
            override = _has_explicit_domain_evidence(evidence, cause_domain)
            if (
                relevance <= 0.2
                and not override
                and not in_domain_exists
                and domain_classification.domain != InvestigationDomain.GENERIC
                and domain_classification.domain_confidence >= 0.4
            ):
                objective_mismatch = True

    missing_evidence = identify_missing_evidence(evidence, tool_outputs, category=category)
    if category == "authentication" and not _auth_failure_signals(evidence, tool_outputs):
        missing_evidence = list(
            dict.fromkeys(
                missing_evidence
                + ["No active 40101, missing_credentials, or credential misconfiguration found in current evidence"]
            )
        )
    independent_sources = count_independent_sources(evidence)
    if independent_sources < 2 and not has_direct_evidence(evidence, tool_outputs):
        missing_evidence = list(
            dict.fromkeys(
                missing_evidence
                + [
                    "Need at least 2 independent evidence sources or 1 direct high-confidence observation"
                ]
            )
        )

    status = validate_investigation_report_fields(
        root_cause=root_cause,
        evidence=evidence,
        confidence=confidence,
        recommended_fix=recommended_fix,
        collector_status=collector_status,
        collector_failure_reasons=failures,
        tool_outputs=tool_outputs,
        category=category,
        template_id=template_id,
    )

    if objective_mismatch and status == InvestigationStatus.COMPLETED and root_cause:
        status = InvestigationStatus.INSUFFICIENT_EVIDENCE
        missing_evidence = list(
            dict.fromkeys(
                missing_evidence
                + [
                    f"No in-domain root cause for {domain_value}; "
                    f"evidence points to {classify_cause_domain(root_cause).value}"
                ]
            )
        )

    synthesis = build_synthesis(
        objective=objective,
        evidence=evidence,
        root_cause=root_cause,
        impact=impact,
        next_action=next_action,
        confidence=confidence,
        missing_evidence=missing_evidence if status != InvestigationStatus.COMPLETED else [],
    )
    if domain_value:
        synthesis["domain"] = domain_value
    if confidence_breakdown:
        synthesis["confidence_breakdown"] = confidence_breakdown
    if recommendation_plan:
        synthesis["recommendation_plan"] = recommendation_plan

    return InvestigationReport(
        investigation_id=investigation_id,
        objective=objective,
        category=category,
        template_id=template_id,
        status=status,
        summary="\n".join(summary_lines),
        evidence=evidence,
        root_cause=root_cause,
        confidence=confidence,
        ranked_causes=ranked_causes,
        impact=impact,
        recommended_fix=recommended_fix,
        verification_steps=verification_steps,
        next_action=next_action,
        created_at=created_at,
        tool_results=tool_results,
        collector_failures=failures,
        resolution_status=classification.resolution if classification else None,
        synthesis=synthesis,
        missing_evidence=missing_evidence if status != InvestigationStatus.COMPLETED else [],
        domain=domain_value,
        confidence_breakdown=confidence_breakdown,
        recommendation_plan=recommendation_plan,
    )


def validate_investigation_report_fields(
    *,
    root_cause: str | None,
    evidence: list[EvidenceItem],
    confidence: float,
    recommended_fix: str,
    collector_status: InvestigationStatus | None = None,
    collector_failure_reasons: list[str] | None = None,
    tool_outputs: list[dict[str, Any]] | None = None,
    category: str = "",
    template_id: str = "",
) -> InvestigationStatus:
    """Return COMPLETED only when evidence is sufficient and conclusion is specific."""
    if collector_status in (InvestigationStatus.FAILED, InvestigationStatus.PARTIAL_FAILURE):
        return collector_status

    if collector_failure_reasons:
        return InvestigationStatus.PARTIAL_FAILURE

    substantive = [item for item in evidence if is_substantive_evidence(item)]
    if not substantive:
        return InvestigationStatus.INSUFFICIENT_EVIDENCE

    if not _is_meaningful_root_cause(root_cause):
        return InvestigationStatus.INSUFFICIENT_EVIDENCE

    if not _is_present(recommended_fix) or confidence <= 0:
        return InvestigationStatus.INSUFFICIENT_EVIDENCE

    # Reject mismatch-resolution cause when investigation is not dashboard/mismatch scoped.
    if (
        root_cause == _RESOLVED_MISMATCH_CAUSE
        and template_id not in ("dashboard_exchange_mismatch", "open_orders_zero_dashboard", "open_orders_empty")
    ):
        return InvestigationStatus.INSUFFICIENT_EVIDENCE

    independent_sources = count_independent_sources(evidence)
    direct = has_direct_evidence(evidence, tool_outputs)
    if independent_sources < 2 and not direct:
        return InvestigationStatus.INSUFFICIENT_EVIDENCE

    return InvestigationStatus.COMPLETED


def validate_investigation_report(report: InvestigationReport) -> InvestigationStatus:
    return validate_investigation_report_fields(
        root_cause=report.root_cause,
        evidence=report.evidence,
        confidence=report.confidence,
        recommended_fix=report.recommended_fix,
    )
