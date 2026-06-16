"""Structured evidence model for production diagnostic investigations."""

from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

ConfidenceLevel = Literal["high", "medium", "low"]

CONFIDENCE_WEIGHTS: dict[str, float] = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}

_TABLE_FROM_QUERY_RE = re.compile(
    r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)


class EvidenceItemRequired(TypedDict):
    source: str
    reference: str
    detail: str
    confidence: ConfidenceLevel


class EvidenceItem(EvidenceItemRequired, total=False):
    """Structured evidence with optional diagnostic metadata."""

    evidence_type: str
    table: str
    row_count: int
    order_ids: list[str]
    timestamps: list[str]
    exchange_response_code: str | int
    log_source: str
    log_container: str
    file_path: str
    line_number: str | int
    is_direct: bool
    artifact_id: str
    content_url: str
    mime_type: str


_WEAK_EVIDENCE_SOURCES = frozenset({"runtime", "unknown"})
_MIN_SUBSTANTIVE_DETAIL = 20


def _extract_table_from_query(query: str) -> str:
    match = _TABLE_FROM_QUERY_RE.search(query or "")
    return match.group(1) if match else ""


def _extract_order_ids(rows: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
    ids: list[str] = []
    for row in rows[:limit]:
        for key in ("exchange_order_id", "id", "order_id"):
            val = row.get(key)
            if val is not None and str(val).strip():
                ids.append(str(val))
                break
    return ids


def _extract_timestamps(rows: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    ts: list[str] = []
    for row in rows[:limit]:
        for key in ("created_at", "updated_at", "timestamp", "checked_at"):
            val = row.get(key)
            if val is not None and str(val).strip():
                ts.append(str(val))
                break
    return ts


def normalize_evidence(raw: Any) -> EvidenceItem | None:
    """Normalize a loose dict into a validated evidence item."""
    if not isinstance(raw, dict):
        return None
    detail = str(raw.get("detail") or "").strip()
    if not detail:
        return None
    confidence = str(raw.get("confidence") or "medium").lower()
    if confidence not in CONFIDENCE_WEIGHTS:
        confidence = "medium"
    item: EvidenceItem = {
        "source": str(raw.get("source") or "unknown"),
        "reference": str(raw.get("reference") or ""),
        "detail": detail[:800],
        "confidence": confidence,  # type: ignore[typeddict-item]
    }
    for key in (
        "evidence_type",
        "table",
        "row_count",
        "order_ids",
        "timestamps",
        "exchange_response_code",
        "log_source",
        "log_container",
        "file_path",
        "line_number",
        "is_direct",
        "artifact_id",
        "content_url",
        "mime_type",
    ):
        if key in raw and raw[key] is not None:
            item[key] = raw[key]  # type: ignore[literal-required]
    return item


def merge_evidence(*collections: list[EvidenceItem] | list[dict[str, Any]] | None) -> list[EvidenceItem]:
    """Merge evidence lists, deduplicating by source+reference+detail prefix."""
    merged: list[EvidenceItem] = []
    seen: set[str] = set()
    for collection in collections:
        for raw in collection or []:
            item = normalize_evidence(raw)
            if item is None:
                continue
            key = f"{item['source']}|{item['reference']}|{item['detail'][:120]}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def evidence_weight(item: EvidenceItem) -> float:
    return CONFIDENCE_WEIGHTS.get(item.get("confidence", "medium"), 0.6)


def is_substantive_evidence(item: EvidenceItem) -> bool:
    """Return True when evidence carries diagnostic signal beyond bare health checks."""
    source = item.get("source", "unknown")
    detail = item.get("detail", "")
    detail_lower = detail.lower()
    if item.get("is_direct"):
        return True
    if source == "runtime" and "health check" in detail_lower:
        return False
    if source in _WEAK_EVIDENCE_SOURCES and len(detail) < _MIN_SUBSTANTIVE_DETAIL:
        return False
    if item.get("row_count", 0) > 0 or item.get("order_ids") or item.get("exchange_response_code"):
        return True
    return len(detail) >= _MIN_SUBSTANTIVE_DETAIL


def count_independent_sources(evidence: list[EvidenceItem]) -> int:
    """Count distinct evidence sources with substantive diagnostic content."""
    sources: set[str] = set()
    for item in evidence:
        if is_substantive_evidence(item):
            sources.add(item["source"])
    return len(sources)


def has_direct_evidence(
    evidence: list[EvidenceItem],
    tool_outputs: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True when at least one high-confidence direct observation exists."""
    for item in evidence:
        if item.get("is_direct") and item.get("confidence") == "high":
            return True
    for output in tool_outputs or []:
        if output.get("ok") is False:
            continue
        if output.get("counts"):
            return True
        if output.get("root_cause") and output.get("tool") in (
            "reconcile_crypto_com_open_orders",
            "diagnose_open_orders",
        ):
            return True
        if output.get("query_executed") and output.get("row_count", 0) > 0:
            return True
    return False


def identify_missing_evidence(
    evidence: list[EvidenceItem],
    tool_outputs: list[dict[str, Any]] | None = None,
    *,
    category: str = "",
) -> list[str]:
    """List evidence gaps that prevented a stronger conclusion."""
    missing: list[str] = []
    sources = {item["source"] for item in evidence if is_substantive_evidence(item)}
    tools_run = {str(o.get("tool")) for o in (tool_outputs or [])}

    if "database" not in sources and "query_database" not in tools_run:
        missing.append("No database query evidence (table counts or order rows)")
    if "logs" not in sources and "search_logs" not in tools_run:
        missing.append("No log search evidence with error/sync context")
    if category in ("orders", "dashboard", "exchange") and "exchange" not in sources:
        if "reconcile_crypto_com_open_orders" not in tools_run and "diagnose_open_orders" not in tools_run:
            missing.append("No live exchange reconciliation or open-order diagnostic")
    if category == "authentication" and "authentication" not in sources:
        missing.append("No credential or auth-error diagnostics from logs or runtime")
    if category == "portfolio" and "exchange" not in sources:
        missing.append("No exchange account summary or equity field comparison")

    substantive_count = sum(1 for item in evidence if is_substantive_evidence(item))
    if substantive_count == 0:
        missing.append("All collected evidence was generic or meta-only")

    return missing


def evidence_from_tool_output(output: dict[str, Any]) -> list[EvidenceItem]:
    """Extract structured evidence from a diagnostic tool output dict."""
    items: list[EvidenceItem] = []
    structured = output.get("evidence")
    if isinstance(structured, list):
        for row in structured:
            item = normalize_evidence(row)
            if item:
                items.append(item)

    tool = str(output.get("tool") or "")
    checked_at = output.get("checked_at")

    if tool == "query_database" and output.get("ok"):
        query = str(output.get("query_executed") or "")
        table = _extract_table_from_query(query)
        row_count = int(output.get("row_count") or 0)
        rows = output.get("rows") or []
        order_ids = _extract_order_ids(rows)
        timestamps = _extract_timestamps(rows) or ([checked_at] if checked_at else [])
        preset = output.get("preset") or "query"
        detail_parts = [f"table={table or 'unknown'}", f"row_count={row_count}"]
        if order_ids:
            detail_parts.append(f"order_ids={order_ids[:5]}")
        if timestamps:
            detail_parts.append(f"timestamps={timestamps[:3]}")
        detail_parts.append(f"query={query[:200]}")
        items.append(
            {
                "source": "database",
                "reference": preset,
                "detail": "; ".join(detail_parts),
                "confidence": "high",
                "evidence_type": "database",
                "table": table,
                "row_count": row_count,
                "order_ids": order_ids,
                "timestamps": timestamps,
                "is_direct": row_count > 0,
            }
        )
        if output.get("status_counts"):
            status_detail = ", ".join(
                f"{k}={v}" for k, v in list(output["status_counts"].items())[:8]
            )
            items.append(
                {
                    "source": "database",
                    "reference": "status_breakdown",
                    "detail": f"table={table or 'exchange_orders'}; status_counts: {status_detail}",
                    "confidence": "high",
                    "evidence_type": "database",
                    "table": table or "exchange_orders",
                    "row_count": row_count,
                    "is_direct": True,
                }
            )

    if tool == "search_logs":
        matches = output.get("matches") or []
        match_count = int(output.get("match_count") or len(matches))
        services = output.get("services_searched") or []
        for match in matches[:5]:
            if not isinstance(match, dict):
                continue
            ts = match.get("timestamp") or checked_at or ""
            source = match.get("source") or "logs"
            message = str(match.get("message") or "")[:300]
            items.append(
                {
                    "source": "logs",
                    "reference": source,
                    "detail": f"[{ts}] container={source}: {message}",
                    "confidence": "medium",
                    "evidence_type": "log",
                    "log_source": source,
                    "log_container": source,
                    "timestamps": [ts] if ts else [],
                }
            )
        if match_count == 0:
            items.append(
                {
                    "source": "logs",
                    "reference": "search_logs",
                    "detail": (
                        f"No log matches for keywords={output.get('keywords', [])} "
                        f"in services={services}; match_count=0"
                    ),
                    "confidence": "low",
                    "evidence_type": "log",
                    "row_count": 0,
                }
            )

    if tool == "search_repository":
        matches = output.get("matches") or []
        for match in matches[:5]:
            if not isinstance(match, dict):
                continue
            path = str(match.get("path") or "")
            line = match.get("line") or ""
            text = str(match.get("text") or "")[:200]
            topic = match.get("topic") or ""
            items.append(
                {
                    "source": "repository",
                    "reference": path,
                    "detail": f"{path}:{line} — {text}",
                    "confidence": str(match.get("confidence") or "medium"),  # type: ignore[typeddict-item]
                    "evidence_type": "repository",
                    "file_path": path,
                    "line_number": line,
                }
            )
        if not matches:
            items.append(
                {
                    "source": "repository",
                    "reference": "search_repository",
                    "detail": f"No repository matches for topics={output.get('topics', [])}",
                    "confidence": "low",
                    "evidence_type": "repository",
                    "row_count": 0,
                }
            )

    if tool == "reconcile_crypto_com_open_orders":
        counts = output.get("counts") or {}
        if counts:
            items.append(
                {
                    "source": "exchange",
                    "reference": "reconciliation_counts",
                    "detail": (
                        f"Exchange={counts.get('exchange_live', 0)}, "
                        f"DB={counts.get('database_open', 0)}, "
                        f"dashboard={counts.get('dashboard_cache', 0)}"
                        + (f"; checked_at={checked_at}" if checked_at else "")
                    ),
                    "confidence": "high",
                    "evidence_type": "exchange",
                    "is_direct": True,
                }
            )
        sources = output.get("sources") or {}
        exchange_meta = sources.get("exchange") or {}
        if exchange_meta.get("trigger_orders_error_code"):
            code = exchange_meta.get("trigger_orders_error_code")
            items.append(
                {
                    "source": "exchange",
                    "reference": "trigger_orders_api",
                    "detail": (
                        f"Trigger-order API error_code={code}: "
                        f"{exchange_meta.get('trigger_orders_error')}"
                    ),
                    "confidence": "high",
                    "evidence_type": "exchange",
                    "exchange_response_code": code,
                    "is_direct": True,
                }
            )
        cred_diag = exchange_meta.get("credential_diagnostics") or {}
        present_pairs = [
            k.replace("_PRESENT", "")
            for k, v in cred_diag.items()
            if k.endswith("_PRESENT") and v
        ]
        if len(present_pairs) > 2:
            items.append(
                {
                    "source": "authentication",
                    "reference": "credential_pairs",
                    "detail": f"Multiple credential env vars present: {present_pairs}",
                    "confidence": "high",
                    "evidence_type": "authentication",
                    "is_direct": True,
                }
            )
        sync_status = output.get("sync_status") or exchange_meta.get("sync_status")
        if sync_status in ("api_error", "failed_auth", "missing_credentials"):
            items.append(
                {
                    "source": "authentication",
                    "reference": "sync_status",
                    "detail": (
                        f"Exchange sync_status={sync_status}; "
                        f"error={exchange_meta.get('error') or output.get('error') or 'not verified'}"
                    ),
                    "confidence": "high",
                    "evidence_type": "authentication",
                    "is_direct": True,
                }
            )
        if exchange_meta.get("error") and "credential" in str(exchange_meta.get("error")).lower():
            items.append(
                {
                    "source": "authentication",
                    "reference": "exchange_fetch",
                    "detail": f"Exchange fetch error: {exchange_meta.get('error')}",
                    "confidence": "high",
                    "evidence_type": "authentication",
                    "is_direct": True,
                }
            )

    if tool == "diagnose_open_orders":
        counts_detail = (
            f"exchange_total={output.get('exchange_total_count')}, "
            f"regular={output.get('exchange_regular_count')}, "
            f"trigger={output.get('exchange_trigger_count')}, "
            f"cache_raw={output.get('cache_raw_count')}, "
            f"dashboard_effective={output.get('dashboard_effective_count')} "
            f"(source={output.get('dashboard_source')})"
            + (f"; checked_at={checked_at}" if checked_at else "")
        )
        items.append(
            {
                "source": "diagnostic",
                "reference": "open_orders_counts",
                "detail": counts_detail,
                "confidence": "high",
                "evidence_type": "diagnostic",
                "is_direct": True,
            }
        )
        if output.get("trigger_orders_error"):
            code = output.get("trigger_orders_error_code")
            items.append(
                {
                    "source": "exchange",
                    "reference": "trigger_orders_api",
                    "detail": (
                        f"Trigger-order API error_code={code}: "
                        f"{output.get('trigger_orders_error')}"
                    ),
                    "confidence": "high",
                    "evidence_type": "exchange",
                    "exchange_response_code": code,
                    "is_direct": True,
                }
            )

    if tool == "inspect_health":
        status = output.get("status")
        if status:
            items.append(
                {
                    "source": "runtime",
                    "reference": "health_endpoint",
                    "detail": f"Health check status={status}",
                    "confidence": "high" if status in ("healthy", "pass") else "medium",
                    "evidence_type": "runtime",
                }
            )

    if output.get("root_cause"):
        items.append(
            {
                "source": "diagnostic",
                "reference": tool or "tool",
                "detail": str(output["root_cause"]),
                "confidence": "high",
                "evidence_type": "diagnostic",
                "is_direct": True,
            }
        )

    return items
