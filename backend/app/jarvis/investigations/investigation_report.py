"""Investigation report format, validation, and root-cause ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.jarvis.investigations.evidence_model import (
    EvidenceItem,
    evidence_weight,
    merge_evidence,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus

_EMPTY_VALUES = frozenset({"", "none", "null", "n/a", "not determined", "unknown"})


@dataclass
class RootCauseCandidate:
    cause: str
    score: float
    supporting_evidence: list[str] = field(default_factory=list)
    explanation: str = ""


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

    def to_dict(self) -> dict[str, Any]:
        return {
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
        }


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in _EMPTY_VALUES


# Known production root-cause patterns with matchers.
_KNOWN_CAUSE_PATTERNS: list[dict[str, Any]] = [
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
    cache_raw = int((diagnose or {}).get("cache_raw_count") or diagnose.get("cache_open_count") or 0)

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
        if not any(c.cause == reconcile_cause for c in filtered):
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
) -> list[RootCauseCandidate]:
    """Score and rank root cause candidates from collected evidence."""
    corpus = _evidence_corpus(evidence, tool_outputs)
    candidates: list[RootCauseCandidate] = []

    for pattern_def in _KNOWN_CAUSE_PATTERNS:
        pat_category = pattern_def.get("category", "")
        if pat_category and pat_category != category and category not in ("api", "dashboard"):
            category_bonus = 0.0
        else:
            category_bonus = 5.0

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
    return deduped[:8]


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

    top = ranked_causes[0] if ranked_causes else None
    min_score = 15.0 if category == "portfolio" else 25.0
    root_cause = top.cause if top and top.score >= min_score else None
    confidence = top.score if top else 0.0

    if root_cause:
        recommended_fix, impact, verification_steps = _lookup_fix_for_cause(root_cause)
    else:
        recommended_fix = "Collect additional evidence from database, logs, and exchange APIs."
        impact = "Unable to determine production impact without sufficient evidence."
        verification_steps = ["Re-run investigation with expanded log access."]

    # Build summary from evidence highlights.
    summary_lines = [objective]
    for item in evidence[:4]:
        summary_lines.append(f"- {item['detail'][:120]}")
    if root_cause:
        summary_lines.append(f"Likely cause: {root_cause}")
    if failures:
        summary_lines.append(f"Collector failures: {'; '.join(failures[:3])}")

    next_action = recommended_fix
    for output in tool_outputs or []:
        if _is_present(output.get("next_action")):
            next_action = str(output["next_action"])
            break

    status = validate_investigation_report_fields(
        root_cause=root_cause,
        evidence=evidence,
        confidence=confidence,
        recommended_fix=recommended_fix,
        collector_status=collector_status,
        collector_failure_reasons=failures,
    )

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
    )


def validate_investigation_report_fields(
    *,
    root_cause: str | None,
    evidence: list[EvidenceItem],
    confidence: float,
    recommended_fix: str,
    collector_status: InvestigationStatus | None = None,
    collector_failure_reasons: list[str] | None = None,
) -> InvestigationStatus:
    """Return COMPLETED only when mandatory collectors succeeded and fields are present."""
    if collector_status in (InvestigationStatus.FAILED, InvestigationStatus.PARTIAL_FAILURE):
        return collector_status

    if collector_failure_reasons:
        return InvestigationStatus.PARTIAL_FAILURE

    if (
        _is_present(root_cause)
        and evidence
        and confidence > 0
        and _is_present(recommended_fix)
    ):
        return InvestigationStatus.COMPLETED
    return InvestigationStatus.INSUFFICIENT_EVIDENCE


def validate_investigation_report(report: InvestigationReport) -> InvestigationStatus:
    return validate_investigation_report_fields(
        root_cause=report.root_cause,
        evidence=report.evidence,
        confidence=report.confidence,
        recommended_fix=report.recommended_fix,
    )
